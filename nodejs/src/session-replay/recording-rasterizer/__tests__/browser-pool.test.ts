import { Browser, Page } from 'puppeteer'

import { BrowserPool } from '~/session-replay/recording-rasterizer/capture/browser-pool'

jest.mock('~/session-replay/recording-rasterizer/logger', () => {
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

const ORIGINAL_ENV = process.env

function mockBrowser(): jest.Mocked<Browser> {
    return {
        newPage: jest.fn(),
        close: jest.fn(),
        connected: true,
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
        process.env = { ...ORIGINAL_ENV }
        delete process.env.HTTPS_PROXY
        delete process.env.HTTP_PROXY
        delete process.env.https_proxy
        delete process.env.http_proxy
        delete process.env.RASTERIZER_USE_PROXY
    })

    afterEach(async () => {
        await pool?.shutdown()
        process.env = ORIGINAL_ENV
    })

    it('launches a browser on getPage with no --proxy-server when no proxy env is set', async () => {
        const browser = mockBrowser()
        const page = mockPage()
        browser.newPage.mockResolvedValue(page)
        puppeteerCapture.launch.mockResolvedValue(browser)

        pool = new BrowserPool(100)
        const result = await pool.getPage()

        expect(puppeteerCapture.launch).toHaveBeenCalledTimes(1)
        expect(result).toBe(page)
        expect(pool.stats).toEqual({ usageCount: 1, activePages: 1 })
        const launchArgs = puppeteerCapture.launch.mock.calls[0][0].args as string[]
        expect(launchArgs.some((a) => a.startsWith('--proxy-server'))).toBe(false)
        expect(launchArgs).toContain('--crash-dumps-dir=/tmp/chrome-crash-dumps')
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

    it('discards a dead idle browser and launches a fresh one', async () => {
        // A browser can crash while parked idle; handing out a page from it
        // throws Puppeteer's "Session closed". The pool must drop it instead.
        const dead = mockBrowser()
        const fresh = mockBrowser()
        dead.newPage.mockResolvedValue(mockPage())
        fresh.newPage.mockResolvedValue(mockPage())
        puppeteerCapture.launch.mockResolvedValueOnce(dead).mockResolvedValueOnce(fresh)

        pool = new BrowserPool(100)
        const p1 = await pool.getPage()
        await pool.releasePage(p1)

        // Browser dies while idle in the pool.
        ;(dead as any).connected = false

        const p2 = await pool.getPage()

        expect(dead.close).toHaveBeenCalled()
        expect(dead.newPage).toHaveBeenCalledTimes(1) // only the first, live acquisition
        expect(puppeteerCapture.launch).toHaveBeenCalledTimes(2)
        await pool.releasePage(p2)
    })

    it('relaunches when newPage throws on a reused browser', async () => {
        // Guards the race where the browser dies between the liveness check
        // and newPage — the crash must not propagate into the render.
        const flaky = mockBrowser()
        const fresh = mockBrowser()
        flaky.newPage.mockRejectedValue(new Error('Protocol error: Session closed'))
        const page = mockPage()
        fresh.newPage.mockResolvedValue(page)
        puppeteerCapture.launch.mockResolvedValueOnce(flaky).mockResolvedValueOnce(fresh)

        pool = new BrowserPool(100)
        const result = await pool.getPage()

        expect(result).toBe(page)
        expect(flaky.close).toHaveBeenCalled()
        expect(puppeteerCapture.launch).toHaveBeenCalledTimes(2)
        await pool.releasePage(result)
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

    describe('proxy resolution', () => {
        it.each([
            { source: 'HTTPS_PROXY', env: 'HTTPS_PROXY' as const },
            { source: 'HTTP_PROXY fallback', env: 'HTTP_PROXY' as const },
            { source: 'lowercase https_proxy', env: 'https_proxy' as const },
            { source: 'lowercase http_proxy', env: 'http_proxy' as const },
        ])('points Chrome at upstream from $source', async ({ env }) => {
            process.env[env] = 'http://smokescreen.smokescreen.svc.cluster.local:4750/'
            const browser = mockBrowser()
            browser.newPage.mockResolvedValue(mockPage())
            puppeteerCapture.launch.mockResolvedValue(browser)

            pool = new BrowserPool(100)
            await pool.launch()

            const launchArgs = puppeteerCapture.launch.mock.calls[0][0].args as string[]
            expect(launchArgs).toContain('--proxy-server=http://smokescreen.smokescreen.svc.cluster.local:4750')
            // Override Chrome's implicit loopback bypass so loopback /
            // link-local destinations still go through the proxy.
            expect(launchArgs).toContain('--proxy-bypass-list=<-loopback>')
        })

        it.each(['smokescreen:4750', 'not a url'])(
            'throws fast at construction when proxy env var %j is not a valid URL with a host',
            (value) => {
                process.env.HTTPS_PROXY = value
                expect(() => new BrowserPool(100)).toThrow()
            }
        )

        it('strips userinfo and path from upstream when forming --proxy-server', async () => {
            process.env.HTTPS_PROXY = 'http://user:pass@smokescreen:4750/somepath'
            const browser = mockBrowser()
            browser.newPage.mockResolvedValue(mockPage())
            puppeteerCapture.launch.mockResolvedValue(browser)

            pool = new BrowserPool(100)
            await pool.launch()

            const launchArgs = puppeteerCapture.launch.mock.calls[0][0].args as string[]
            expect(launchArgs).toContain('--proxy-server=http://smokescreen:4750')
            // Make sure nothing matching user:pass leaked
            expect(launchArgs.find((a) => a.includes('user:pass'))).toBeUndefined()
        })

        it.each(['false', 'False', 'FALSE', '0', 'no', 'off', ' false '])(
            'RASTERIZER_USE_PROXY=%j short-circuits the proxy even when HTTPS_PROXY is set',
            async (value) => {
                process.env.HTTPS_PROXY = 'http://smokescreen:4750/'
                process.env.RASTERIZER_USE_PROXY = value
                const browser = mockBrowser()
                browser.newPage.mockResolvedValue(mockPage())
                puppeteerCapture.launch.mockResolvedValue(browser)

                pool = new BrowserPool(100)
                await pool.launch()

                const launchArgs = puppeteerCapture.launch.mock.calls[0][0].args as string[]
                expect(launchArgs.some((a) => a.startsWith('--proxy-server'))).toBe(false)
                expect(launchArgs.some((a) => a.startsWith('--proxy-bypass-list'))).toBe(false)
            }
        )

        it.each(['true', '1', '', 'enabled', 'disabled', 'yes'])(
            'RASTERIZER_USE_PROXY=%j leaves proxy on (only known falsy values disable)',
            async (value) => {
                process.env.HTTPS_PROXY = 'http://smokescreen:4750/'
                if (value !== '') {
                    process.env.RASTERIZER_USE_PROXY = value
                }
                const browser = mockBrowser()
                browser.newPage.mockResolvedValue(mockPage())
                puppeteerCapture.launch.mockResolvedValue(browser)

                pool = new BrowserPool(100)
                await pool.launch()

                const launchArgs = puppeteerCapture.launch.mock.calls[0][0].args as string[]
                expect(launchArgs).toContain('--proxy-server=http://smokescreen:4750')
            }
        )
    })
})
