import type { Page, StagehandBrowser } from '@browserbasehq/stagehand'
import type { BrowserType } from '@playwright/test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { realpathSync } from 'node:fs'
import path from 'node:path'

export async function launchStagehand(
    chromium: BrowserType,
    viewport: { width: number; height: number },
    port: number
): Promise<{ browser: StagehandBrowser; page: Page; close: () => Promise<void> }> {
    // Stagehand exports an ESM entrypoint; Playwright loads these specs as CommonJS.
    const { localBrowser, Stagehand } = await import('@browserbasehq/stagehand')
    const extensionPath = realpathSync(
        path.join(__dirname, 'node_modules', '@browserbasehq', 'stagehand', 'dist', 'extension')
    )
    // Chromium derives unpacked extension IDs from the path, using the first 16 SHA256 bytes and the a-p alphabet.
    const extensionId = createHash('sha256')
        .update(extensionPath)
        .digest('hex')
        .slice(0, 32)
        .replace(/[0-9a-f]/g, (digit) => String.fromCharCode(97 + Number.parseInt(digit, 16)))
    const chrome = await chromium.launch({
        executablePath: chromium.executablePath(),
        headless: true,
        ignoreDefaultArgs: ['--disable-extensions'],
        args: [
            `--remote-debugging-port=${port}`,
            '--enable-unsafe-extension-debugging',
            `--remote-allow-origins=chrome-extension://${extensionId}`,
        ],
    })
    let browser: StagehandBrowser | undefined
    let client: Awaited<ReturnType<typeof Stagehand.create>> | undefined
    const close = async (): Promise<void> => {
        try {
            await client?.close()
            await browser?.close()
        } finally {
            await chrome.close()
        }
    }
    try {
        // Chrome 148 permits Extensions.loadUnpacked over the launcher's pipe, but rejects TCP clients.
        const cdp = await chrome.newBrowserCDPSession()
        const { id } = await cdp.send('Extensions.loadUnpacked', {
            path: extensionPath,
        })
        assert.equal(id, extensionId, 'Chrome extension ID differs from the origin allowlist')
        await cdp.detach()
        browser = await localBrowser.connect({ cdpUrl: `http://127.0.0.1:${port}`, extensionId: id })
        client = await Stagehand.create({ browser })
        const page = (await browser.context.activePage()) ?? (await browser.context.newPage())
        await page.setViewportSize(viewport.width, viewport.height)
        return { browser, page, close }
    } catch (error) {
        await close()
        if (error instanceof Error)
            throw new Error(`${error.message}; CDP cause: ${JSON.stringify(error.cause)}`, { cause: error })
        throw error
    }
}
