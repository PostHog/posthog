import { devices, expect, type Page } from '@playwright/test'

const providerUrl = 'https://dns.example.com/connect'

async function testDomainConnect(page: Page, storyId: string, blocked: boolean): Promise<void> {
    const browser = page.context().browser()
    if (!browser) {
        throw new Error('Domain Connect acceptance requires a browser')
    }
    expect(browser.browserType().name()).toBe('webkit')
    const context = await browser.newContext({ ...devices['iPhone 12'] })
    try {
        await context.route(providerUrl, (route) =>
            route.fulfill({ contentType: 'text/html', body: '<h1>DNS setup</h1>' })
        )
        const mobilePage = await context.newPage()
        const url = new URL('/iframe.html', page.url())
        url.searchParams.set('id', storyId)
        url.searchParams.set('viewMode', 'story')
        await mobilePage.goto(url.toString())
        const configure = mobilePage.getByRole('button', { name: 'Configure automatically' })
        await expect(configure).toBeVisible()
        if (blocked) {
            await mobilePage.evaluate(() => {
                window.open = () => null
            })
            await configure.click()
            await mobilePage.waitForFunction(
                () => document.documentElement.dataset.domainConnectResponsePending === 'true'
            )
            await mobilePage.evaluate(() => window.dispatchEvent(new Event('release-domain-connect-response')))
            await expect(mobilePage).toHaveURL(providerUrl)
            await expect(mobilePage.getByRole('heading', { name: 'DNS setup' })).toBeVisible()
        } else {
            const popupOpened = context.waitForEvent('page', { timeout: 5000 })
            await configure.click()
            const popup = await popupOpened
            expect(popup.url()).toBe('about:blank')
            await mobilePage.waitForFunction(
                () => document.documentElement.dataset.domainConnectResponsePending === 'true'
            )
            await mobilePage.evaluate(() => window.dispatchEvent(new Event('release-domain-connect-response')))
            await expect(popup).toHaveURL(providerUrl)
            await expect(popup.getByRole('heading', { name: 'DNS setup' })).toBeVisible()
            await expect(mobilePage).toHaveURL(url.toString())
        }
    } finally {
        await context.close()
    }
}

export const domainConnectBrowserTests: Record<string, (page: Page) => Promise<void>> = {
    'components-domain-connect--mobile-popup': (page) =>
        testDomainConnect(page, 'components-domain-connect--mobile-popup', false),
    'components-domain-connect--mobile-fallback': (page) =>
        testDomainConnect(page, 'components-domain-connect--mobile-fallback', true),
}
