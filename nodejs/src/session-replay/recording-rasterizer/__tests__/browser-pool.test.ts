import { Browser, Page } from 'puppeteer'

import { BrowserPool } from '../browser-pool'

jest.mock('puppeteer', () => ({
    launch: jest.fn(),
}))

const puppeteer = require('puppeteer')

function mockBrowser(): jest.Mocked<Browser> {
    return {
        newPage: jest.fn(),
        close: jest.fn(),
    } as any
}

function mockPage(): jest.Mocked<Page> {
    return {
        close: jest.fn(),
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

    it('launches browser on first getPage call', async () => {
        const browser = mockBrowser()
        const page = mockPage()
        browser.newPage.mockResolvedValue(page)
        puppeteer.launch.mockResolvedValue(browser)

        pool = new BrowserPool(100)
        const result = await pool.getPage()

        expect(puppeteer.launch).toHaveBeenCalledTimes(1)
        expect(result).toBe(page)
        expect(pool.stats).toEqual({ usageCount: 1, activePages: 1 })
    })

    it('reuses browser across multiple getPage calls', async () => {
        const browser = mockBrowser()
        browser.newPage.mockResolvedValue(mockPage())
        puppeteer.launch.mockResolvedValue(browser)

        pool = new BrowserPool(100)
        const p1 = await pool.getPage()
        const p2 = await pool.getPage()

        expect(puppeteer.launch).toHaveBeenCalledTimes(1)
        expect(pool.stats).toEqual({ usageCount: 2, activePages: 2 })

        await pool.releasePage(p1)
        await pool.releasePage(p2)
        expect(pool.stats.activePages).toBe(0)
    })

    it('recycles browser after recycleAfter threshold when all pages released', async () => {
        const browser1 = mockBrowser()
        const browser2 = mockBrowser()
        browser1.newPage.mockResolvedValue(mockPage())
        browser2.newPage.mockResolvedValue(mockPage())
        puppeteer.launch.mockResolvedValueOnce(browser1).mockResolvedValueOnce(browser2)

        pool = new BrowserPool(2)
        const p1 = await pool.getPage()
        await pool.releasePage(p1)

        // First use — not at threshold yet
        expect(puppeteer.launch).toHaveBeenCalledTimes(1)

        const p2 = await pool.getPage()
        await pool.releasePage(p2)

        // Second use hits threshold, recycle triggered
        expect(browser1.close).toHaveBeenCalled()
        expect(puppeteer.launch).toHaveBeenCalledTimes(2)
    })

    it('does not recycle while pages are still active', async () => {
        const browser = mockBrowser()
        browser.newPage.mockResolvedValue(mockPage())
        puppeteer.launch.mockResolvedValue(browser)

        pool = new BrowserPool(2)
        const p1 = await pool.getPage()
        const p2 = await pool.getPage()

        // At threshold but p1 and p2 still active
        await pool.releasePage(p1)
        expect(browser.close).not.toHaveBeenCalled()

        // Now release last page — recycle should trigger
        await pool.releasePage(p2)
        expect(browser.close).toHaveBeenCalled()
    })

    it('shutdown closes browser', async () => {
        const browser = mockBrowser()
        browser.newPage.mockResolvedValue(mockPage())
        puppeteer.launch.mockResolvedValue(browser)

        pool = new BrowserPool(100)
        await pool.getPage()
        await pool.shutdown()

        expect(browser.close).toHaveBeenCalled()
    })

    it('shutdown is safe to call when no browser exists', async () => {
        pool = new BrowserPool(100)
        await expect(pool.shutdown()).resolves.not.toThrow()
    })

    it('recovers from failed recycle when launch fails', async () => {
        const browser1 = mockBrowser()
        const browser3 = mockBrowser()
        browser1.newPage.mockResolvedValue(mockPage())
        browser3.newPage.mockResolvedValue(mockPage())
        puppeteer.launch
            .mockResolvedValueOnce(browser1)
            .mockRejectedValueOnce(new Error('launch failed'))
            .mockResolvedValueOnce(browser3)

        const consoleSpy = jest.spyOn(console, 'error').mockImplementation()

        pool = new BrowserPool(1)
        const p1 = await pool.getPage()
        await pool.releasePage(p1)

        expect(consoleSpy).toHaveBeenCalledWith('Browser recycle failed:', expect.any(Error))
        consoleSpy.mockRestore()

        // The recycling promise is reset via finally, so getPage can retry
        const p2 = await pool.getPage()
        expect(p2).toBeDefined()
        expect(puppeteer.launch).toHaveBeenCalledTimes(3)
    })

    it('deduplicates concurrent launch calls', async () => {
        const browser = mockBrowser()
        browser.newPage.mockResolvedValue(mockPage())
        puppeteer.launch.mockResolvedValue(browser)

        pool = new BrowserPool(100)
        await Promise.all([pool.launch(), pool.launch(), pool.launch()])

        expect(puppeteer.launch).toHaveBeenCalledTimes(1)
    })

    it('deduplicates concurrent recycle calls', async () => {
        const browser1 = mockBrowser()
        const browser2 = mockBrowser()
        browser1.newPage.mockResolvedValue(mockPage())
        browser2.newPage.mockResolvedValue(mockPage())
        puppeteer.launch.mockResolvedValueOnce(browser1).mockResolvedValueOnce(browser2)

        pool = new BrowserPool(100)
        await pool.launch()
        await Promise.all([pool.recycle(), pool.recycle(), pool.recycle()])

        expect(browser1.close).toHaveBeenCalledTimes(1)
        expect(puppeteer.launch).toHaveBeenCalledTimes(2)
    })
})
