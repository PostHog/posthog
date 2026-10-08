import type { Page, StagehandBrowser } from '@browserbasehq/stagehand'
import type { BrowserType } from '@playwright/test'
import path from 'node:path'

export async function launchStagehand(
    chromium: BrowserType,
    viewport: { width: number; height: number },
    port: number
): Promise<{ browser: StagehandBrowser; page: Page; close: () => Promise<void> }> {
    // Stagehand exports an ESM entrypoint; Playwright loads these specs as CommonJS.
    const { localBrowser, Stagehand } = await import('@browserbasehq/stagehand')
    const chrome = await chromium.launch({
        executablePath: chromium.executablePath(),
        headless: true,
        ignoreDefaultArgs: ['--disable-extensions'],
        args: [`--remote-debugging-port=${port}`, '--enable-unsafe-extension-debugging'],
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
            path: path.join(__dirname, 'node_modules', '@browserbasehq', 'stagehand', 'dist', 'extension'),
        })
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
