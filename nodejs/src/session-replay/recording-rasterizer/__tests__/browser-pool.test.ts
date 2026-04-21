import { Browser, Page } from 'puppeteer'

import { BrowserPool } from '../capture/browser-pool'

jest.mock('../logger', () => {
    const info = jest.fn()
    return {
        __mockLogInfo: info,
        createLogger: () => ({
            info,
            warn: jest.fn(),
            error: jest.fn(),
            debug: jest.fn(),
            child: jest.fn().mockReturnThis(),
        }),
    }
})

jest.mock(
    'puppeteer-capture',
    () => ({
        launch: jest.fn(),
    }),
    { virtual: true }
)

const puppeteerCapture = require('puppeteer-capture')

function mockBrowser(): jest.Mocked<Browser> {
    return {
        newPage: jest.fn(),
        close: jest.fn(),
    } as any
}

function mockPage(): jest.Mocked<Page> {
    return {
        close: jest.fn().mockResolvedValue(undefined),
    } as any
}

describe('BrowserPool', () => {
    let pool: BrowserPool

    beforeEach(() => {
        jest.clearAllMocks()
    })

    afterEach(async () => {
        await pool?.shutdown()
    })

    it('launches a browser on getPage', async () => {
        const browser = mockBrowser()
        const page = mockPage()
        browser.newPage.mockResolvedValue(page)
        puppeteerCapture.launch.mockResolvedValue(browser)

        pool = new BrowserPool(100)
        const result = await pool.getPage()

        expect(puppeteerCapture.launch).toHaveBeenCalledTimes(1)
        expect(result).toBe(page)
        expect(pool.stats).toEqual({ usageCount: 1, activePages: 1 })
    })

    it('launches separate browsers for concurrent pages', async () => {
        const browser1 = mockBrowser()
        const browser2 = mockBrowser()
        browser1.newPage.mockResolvedValue(mockPage())
        browser2.newPage.mockResolvedValue(mockPage())
        puppeteerCapture.launch.mockResolvedValueOnce(browser1).mockResolvedValueOnce(browser2)

        pool = new BrowserPool(100)
        const p1 = await pool.getPage()
        const p2 = await pool.getPage()

        expect(puppeteerCapture.launch).toHaveBeenCalledTimes(2)
        expect(pool.stats).toEqual({ usageCount: 2, activePages: 2 })

        await pool.releasePage(p1)
        await pool.releasePage(p2)
        expect(pool.stats.activePages).toBe(0)
    })

    it('reuses idle browser for sequential getPage calls', async () => {
        const browser = mockBrowser()
        browser.newPage.mockImplementation(() => Promise.resolve(mockPage()))
        puppeteerCapture.launch.mockResolvedValue(browser)

        pool = new BrowserPool(100)
        const p1 = await pool.getPage()
        await pool.releasePage(p1)

        const p2 = await pool.getPage()
        await pool.releasePage(p2)

        expect(puppeteerCapture.launch).toHaveBeenCalledTimes(1)
    })

    it('recycles browser when usage hits recycleAfter', async () => {
        const browser1 = mockBrowser()
        const browser2 = mockBrowser()
        browser1.newPage.mockResolvedValue(mockPage())
        browser2.newPage.mockResolvedValue(mockPage())
        puppeteerCapture.launch.mockResolvedValueOnce(browser1).mockResolvedValueOnce(browser2)

        pool = new BrowserPool(2)
        const p1 = await pool.getPage()
        await pool.releasePage(p1)
        const p2 = await pool.getPage()
        await pool.releasePage(p2)

        // browser1 had 2 uses — should be closed, not returned to idle
        expect(browser1.close).toHaveBeenCalled()

        // Next getPage needs a new browser
        const p3 = await pool.getPage()
        expect(puppeteerCapture.launch).toHaveBeenCalledTimes(2)
        await pool.releasePage(p3)
    })

    it('pre-warms one browser on launch()', async () => {
        const browser = mockBrowser()
        browser.newPage.mockResolvedValue(mockPage())
        puppeteerCapture.launch.mockResolvedValue(browser)

        pool = new BrowserPool(100)
        await pool.launch()

        expect(puppeteerCapture.launch).toHaveBeenCalledTimes(1)

        // getPage should reuse the pre-warmed browser
        await pool.getPage()
        expect(puppeteerCapture.launch).toHaveBeenCalledTimes(1)
    })

    it('shutdown closes all browsers', async () => {
        const browser1 = mockBrowser()
        const browser2 = mockBrowser()
        const page1 = mockPage()
        const page2 = mockPage()
        browser1.newPage.mockResolvedValue(page1)
        browser2.newPage.mockResolvedValue(page2)
        puppeteerCapture.launch.mockResolvedValueOnce(browser1).mockResolvedValueOnce(browser2)

        pool = new BrowserPool(100)
        await pool.getPage()
        await pool.getPage()
        await pool.shutdown()

        expect(page1.close).toHaveBeenCalled()
        expect(page2.close).toHaveBeenCalled()
        expect(pool.stats.activePages).toBe(0)
    })

    it('shutdown is safe to call when no browsers exist', async () => {
        pool = new BrowserPool(100)
        await expect(pool.shutdown()).resolves.not.toThrow()
    })

    it('releaseAllPages closes all tracked pages', async () => {
        const browser1 = mockBrowser()
        const browser2 = mockBrowser()
        const page1 = mockPage()
        const page2 = mockPage()
        browser1.newPage.mockResolvedValue(page1)
        browser2.newPage.mockResolvedValue(page2)
        puppeteerCapture.launch.mockResolvedValueOnce(browser1).mockResolvedValueOnce(browser2)

        pool = new BrowserPool(100)
        await pool.getPage()
        await pool.getPage()
        expect(pool.stats.activePages).toBe(2)

        await pool.releaseAllPages()

        expect(page1.close).toHaveBeenCalled()
        expect(page2.close).toHaveBeenCalled()
        expect(pool.stats.activePages).toBe(0)
    })

    it('releaseAllPages handles already-closed pages gracefully', async () => {
        const browser = mockBrowser()
        const page = mockPage()
        page.close.mockRejectedValue(new Error('page already closed'))
        browser.newPage.mockResolvedValue(page)
        puppeteerCapture.launch.mockResolvedValue(browser)

        pool = new BrowserPool(100)
        await pool.getPage()

        await expect(pool.releaseAllPages()).resolves.not.toThrow()
        expect(pool.stats.activePages).toBe(0)
    })
})
