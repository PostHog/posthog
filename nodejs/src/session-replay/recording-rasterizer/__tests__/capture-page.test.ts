import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'
import { CDPSession, Page } from 'puppeteer'

import { CapturePage, playerHtmlCache } from '../capture/capture-page'

const mockLog = {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
    child: jest.fn().mockReturnThis(),
} as any

const playerUrl = 'http://localhost:8000/player'
const playerHtml = '<html>player</html>'

describe('capture-page', () => {
    let originalSend: jest.Mock

    function createMockPage(): Page {
        originalSend = jest.fn().mockResolvedValue({ data: 'frame-data' })
        const mockSession = { send: originalSend } as unknown as CDPSession
        const mainFrame = { parentFrame: () => null }

        return {
            viewport: jest.fn().mockReturnValue({ width: 1280, height: 720 }),
            setViewport: jest.fn().mockResolvedValue(undefined),
            createCDPSession: jest.fn().mockResolvedValue(mockSession),
            mainFrame: jest.fn().mockReturnValue(mainFrame),
            frames: jest.fn().mockReturnValue([mainFrame]),
            on: jest.fn(),
        } as unknown as Page
    }

    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('CapturePage.prepare', () => {
        it('sets viewport with deviceScaleFactor 1', async () => {
            const page = createMockPage()
            await CapturePage.prepare(page, { width: 1920, height: 1080 }, playerUrl, playerHtml, false, mockLog)

            expect(page.setViewport).toHaveBeenCalledWith({
                width: 1920,
                height: 1080,
                deviceScaleFactor: 1,
            })
        })

        it('exposes playerUrl and playerHtml as readonly properties', async () => {
            const page = createMockPage()
            const capturePage = await CapturePage.prepare(
                page,
                { width: 1280, height: 720 },
                playerUrl,
                playerHtml,
                false,
                mockLog
            )

            expect(capturePage.playerUrl).toBe(playerUrl)
            expect(capturePage.playerHtml).toBe(playerHtml)
        })

        it('hides grandchild frames', async () => {
            const mainFrame = { parentFrame: () => null }
            const childFrame = { parentFrame: () => mainFrame }
            const grandchildFrame = { parentFrame: () => childFrame }
            const page = createMockPage()
            ;(page.mainFrame as jest.Mock).mockReturnValue(mainFrame)
            ;(page.frames as jest.Mock).mockReturnValue([mainFrame, childFrame, grandchildFrame])

            const capturePage = await CapturePage.prepare(
                page,
                { width: 1280, height: 720 },
                playerUrl,
                playerHtml,
                false,
                mockLog
            )

            const frames = capturePage.page.frames()
            expect(frames).toEqual([mainFrame, childFrame])
        })

        it('wires up browser log forwarding when captureLogs is true', async () => {
            const page = createMockPage()
            await CapturePage.prepare(page, { width: 1280, height: 720 }, playerUrl, playerHtml, true, mockLog)

            expect(page.on).toHaveBeenCalledWith('console', expect.any(Function))
            expect(page.on).toHaveBeenCalledWith('pageerror', expect.any(Function))
            expect(page.on).toHaveBeenCalledWith('requestfailed', expect.any(Function))
        })

        it('does not wire up log forwarding when captureLogs is false', async () => {
            const page = createMockPage()
            await CapturePage.prepare(page, { width: 1280, height: 720 }, playerUrl, playerHtml, false, mockLog)

            expect(page.on).not.toHaveBeenCalled()
        })
    })

    describe('installCDPGuards', () => {
        async function preparePage(): Promise<{ page: Page; capturePage: CapturePage }> {
            const page = createMockPage()
            const capturePage = await CapturePage.prepare(
                page,
                { width: 1280, height: 720 },
                playerUrl,
                playerHtml,
                false,
                mockLog
            )
            return { page, capturePage }
        }

        it('injects jpeg format and quality into beginFrame calls', async () => {
            const { page, capturePage } = await preparePage()
            capturePage.installCDPGuards('jpeg', 80, jest.fn().mockResolvedValue(undefined))

            const session = await (page as any).createCDPSession()
            await session.send('HeadlessExperimental.beginFrame', { deadline: 1000 })

            expect(originalSend).toHaveBeenCalledWith('HeadlessExperimental.beginFrame', {
                deadline: 1000,
                screenshot: { format: 'jpeg', quality: 80 },
            })
        })

        it('passes non-beginFrame CDP calls through unchanged', async () => {
            const { page, capturePage } = await preparePage()
            capturePage.installCDPGuards('jpeg', 80, jest.fn().mockResolvedValue(undefined))

            const session = await (page as any).createCDPSession()
            await session.send('Page.navigate', { url: 'http://example.com' })

            expect(originalSend).toHaveBeenCalledWith('Page.navigate', { url: 'http://example.com' })
        })

        it('adds screenshot params even when beginFrame has no existing params', async () => {
            const { page, capturePage } = await preparePage()
            capturePage.installCDPGuards('jpeg', 80, jest.fn().mockResolvedValue(undefined))

            const session = await (page as any).createCDPSession()
            await session.send('HeadlessExperimental.beginFrame')

            expect(originalSend).toHaveBeenCalledWith('HeadlessExperimental.beginFrame', {
                screenshot: { format: 'jpeg', quality: 80 },
            })
        })

        it('does not inject screenshot params when format is png', async () => {
            const { page, capturePage } = await preparePage()
            capturePage.installCDPGuards('png', undefined, jest.fn().mockResolvedValue(undefined))

            const session = await (page as any).createCDPSession()
            await session.send('HeadlessExperimental.beginFrame', { deadline: 1000 })

            expect(originalSend).toHaveBeenCalledWith('HeadlessExperimental.beginFrame', { deadline: 1000 })
        })

        it('waits for requests to settle before each beginFrame', async () => {
            const { page, capturePage } = await preparePage()
            const callOrder: string[] = []
            const waitForSettled = jest.fn().mockImplementation(() => {
                callOrder.push('settled')
                return Promise.resolve()
            })
            originalSend.mockImplementation(() => {
                callOrder.push('send')
                return Promise.resolve({ data: 'frame-data' })
            })

            capturePage.installCDPGuards('jpeg', 80, waitForSettled)

            const session = await (page as any).createCDPSession()
            await session.send('HeadlessExperimental.beginFrame')

            expect(callOrder).toEqual(['settled', 'send'])
        })

        it('does not wait for settled on non-beginFrame calls', async () => {
            const { page, capturePage } = await preparePage()
            const waitForSettled = jest.fn().mockResolvedValue(undefined)
            capturePage.installCDPGuards('jpeg', 80, waitForSettled)

            const session = await (page as any).createCDPSession()
            await session.send('Page.navigate', { url: 'http://example.com' })

            expect(waitForSettled).not.toHaveBeenCalled()
        })
    })

    describe('playerHtmlCache', () => {
        let tmpFile: string

        beforeEach(async () => {
            playerHtmlCache.reset()
            tmpFile = path.join(os.tmpdir(), `test-player-${Date.now()}.html`)
            await fs.writeFile(tmpFile, '<html><body>test player</body></html>')
        })

        afterEach(async () => {
            await fs.rm(tmpFile, { force: true })
        })

        it('loads HTML from the given path', async () => {
            const html = await playerHtmlCache.load(tmpFile)
            expect(html).toBe('<html><body>test player</body></html>')
        })

        it('get() returns cached value after load()', async () => {
            await playerHtmlCache.load(tmpFile)
            expect(playerHtmlCache.get()).toBe('<html><body>test player</body></html>')
        })

        it('load() updates cache when called again', async () => {
            await playerHtmlCache.load(tmpFile)
            await fs.writeFile(tmpFile, '<html>updated</html>')
            await playerHtmlCache.load(tmpFile)
            expect(playerHtmlCache.get()).toBe('<html>updated</html>')
        })

        it('load() rejects when file does not exist', async () => {
            await expect(playerHtmlCache.load('/nonexistent/path/player.html')).rejects.toThrow()
        })

        it('get() throws before load() is called', () => {
            expect(() => playerHtmlCache.get()).toThrow('Player HTML not loaded')
        })

        it('reset() clears the cache', async () => {
            await playerHtmlCache.load(tmpFile)
            playerHtmlCache.reset()
            expect(() => playerHtmlCache.get()).toThrow('Player HTML not loaded')
        })
    })
})
