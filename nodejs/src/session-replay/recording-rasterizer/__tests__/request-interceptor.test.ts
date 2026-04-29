import { Frame, HTTPRequest, Page } from 'puppeteer'

import { BlockProxy } from '../capture/block-proxy'
import { CapturePage } from '../capture/capture-page'
import { RequestInterceptor } from '../capture/request-interceptor'

const mockFetch = jest.fn()
jest.mock('../../../utils/request', () => ({
    fetch: (...args: any[]) => mockFetch(...args),
}))

type PageEventHandler = (req: HTTPRequest) => void

const mainFrame = { name: 'mainFrame' } as unknown as Frame
const subFrame = { name: 'subFrame' } as unknown as Frame

const playerUrl = 'http://localhost:8000/player'
const playerHtml = '<html>player</html>'

function mockPage(): {
    page: Page
    emitRequestFinished: (req: HTTPRequest) => void
    emitRequestFailed: (req: HTTPRequest) => void
} {
    const handlers: Record<string, PageEventHandler[]> = {}
    const page = {
        mainFrame: jest.fn().mockReturnValue(mainFrame),
        on: jest.fn((event: string, handler: PageEventHandler) => {
            handlers[event] = handlers[event] || []
            handlers[event].push(handler)
        }),
        setRequestInterception: jest.fn().mockResolvedValue(undefined),
    } as unknown as Page

    return {
        page,
        emitRequestFinished: (req) => handlers['requestfinished']?.forEach((h) => h(req)),
        emitRequestFailed: (req) => handlers['requestfailed']?.forEach((h) => h(req)),
    }
}

function mockCapturePage(page?: Page): CapturePage {
    const p = page || mockPage().page
    return { page: p, playerUrl, playerHtml } as unknown as CapturePage
}

function mockRequest(type: string, frame: Frame = subFrame, url = 'https://example.com/style.css'): HTTPRequest {
    return {
        resourceType: jest.fn().mockReturnValue(type),
        url: jest.fn().mockReturnValue(url),
        frame: jest.fn().mockReturnValue(frame),
        headers: jest.fn().mockReturnValue({
            accept: 'text/css',
            host: 'example.com',
            connection: 'keep-alive',
            'content-length': '0',
        }),
        respond: jest.fn().mockResolvedValue(undefined),
        abort: jest.fn().mockResolvedValue(undefined),
        continue: jest.fn().mockResolvedValue(undefined),
    } as unknown as HTTPRequest
}

const mockLog = {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
    child: jest.fn().mockReturnThis(),
} as any

function mockBlockProxy(): BlockProxy {
    return {
        handleRequest: jest.fn().mockResolvedValue(undefined),
        fetchBlocks: jest.fn().mockResolvedValue(0),
        blockCount: 0,
    } as unknown as BlockProxy
}

async function createInterceptor(
    page?: Page,
    blockProxy?: BlockProxy
): Promise<{ interceptor: RequestInterceptor; page: ReturnType<typeof mockPage>; blockProxy: BlockProxy }> {
    const mp = page ? { page, emitRequestFinished: () => {}, emitRequestFailed: () => {} } : mockPage()
    const bp = blockProxy || mockBlockProxy()
    const cp = mockCapturePage(mp.page)
    const interceptor = new RequestInterceptor(cp, bp, mockLog)
    await interceptor.install()
    return { interceptor, page: mp as ReturnType<typeof mockPage>, blockProxy: bp }
}

/** Get the 'request' event handler installed by interceptor.install() */
function getRequestHandler(page: Page): (req: HTTPRequest) => void {
    const calls = (page.on as jest.Mock).mock.calls
    const requestCall = calls.find(([event]: [string]) => event === 'request')
    return requestCall[1]
}

describe('RequestInterceptor', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('install', () => {
        it('enables request interception and registers event handlers', async () => {
            const { page } = await createInterceptor()
            expect(page.page.setRequestInterception).toHaveBeenCalledWith(true)
            expect(page.page.on).toHaveBeenCalledWith('request', expect.any(Function))
            expect(page.page.on).toHaveBeenCalledWith('requestfinished', expect.any(Function))
            expect(page.page.on).toHaveBeenCalledWith('requestfailed', expect.any(Function))
        })
    })

    describe('request routing', () => {
        it('serves player HTML for the player URL', async () => {
            const { page } = await createInterceptor()
            const handler = getRequestHandler(page.page)
            const req = mockRequest('document', mainFrame, playerUrl)

            handler(req)

            expect(req.respond).toHaveBeenCalledWith({
                status: 200,
                contentType: 'text/html',
                body: playerHtml,
            })
        })

        it('forwards block requests to BlockProxy', async () => {
            const bp = mockBlockProxy()
            const { page } = await createInterceptor(undefined, bp)
            const handler = getRequestHandler(page.page)
            const req = mockRequest('xhr', mainFrame, 'http://localhost:8000/__blocks/0')

            handler(req)

            expect(bp.handleRequest).toHaveBeenCalledWith(req, '/__blocks/0')
        })

        it('continues main-frame requests without proxying', async () => {
            const { page } = await createInterceptor()
            const handler = getRequestHandler(page.page)
            const req = mockRequest('stylesheet', mainFrame, 'https://cdn.example.com/style.css')

            handler(req)

            expect(req.continue).toHaveBeenCalled()
            expect(req.respond).not.toHaveBeenCalled()
            expect(req.abort).not.toHaveBeenCalled()
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('proxies sub-frame stylesheet requests through Node.js', async () => {
            mockFetch.mockResolvedValue({
                status: 200,
                headers: { 'content-type': 'text/css' },
                text: jest.fn().mockResolvedValue('body { color: red }'),
            })

            const { page } = await createInterceptor()
            const handler = getRequestHandler(page.page)
            const req = mockRequest('stylesheet')

            handler(req)
            await new Promise(process.nextTick)

            expect(mockFetch).toHaveBeenCalledWith('https://example.com/style.css', {
                headers: { accept: 'text/css' },
                timeoutMs: 10_000,
            })
            expect(req.respond).toHaveBeenCalledWith({
                status: 200,
                contentType: 'text/css',
                body: 'body { color: red }',
            })
        })

        it('aborts sub-frame media requests immediately', async () => {
            const { page } = await createInterceptor()
            const handler = getRequestHandler(page.page)
            const req = mockRequest('media')

            handler(req)
            expect(req.abort).toHaveBeenCalled()
            expect(req.respond).not.toHaveBeenCalled()
            expect(req.continue).not.toHaveBeenCalled()
        })

        it.each(['image', 'font', 'script', 'xhr', 'fetch', 'document'])(
            'continues sub-frame %s requests normally',
            async (type) => {
                const { page } = await createInterceptor()
                const handler = getRequestHandler(page.page)
                const req = mockRequest(type)

                handler(req)
                expect(req.continue).toHaveBeenCalled()
                expect(req.abort).not.toHaveBeenCalled()
                expect(req.respond).not.toHaveBeenCalled()
            }
        )

        it.each(['data:text/css;base64,Ym9keSB7fQ==', 'blob:null/abc-123', 'about:blank'])(
            'continues requests with unparseable URL %s',
            async (url) => {
                const { page } = await createInterceptor()
                const handler = getRequestHandler(page.page)
                const req = mockRequest('document', mainFrame, url)

                handler(req)
                expect(req.continue).toHaveBeenCalled()
                expect(req.respond).not.toHaveBeenCalled()
                expect(req.abort).not.toHaveBeenCalled()
            }
        )
    })

    describe('stylesheet proxy', () => {
        it('strips hop-by-hop headers from the proxied request', async () => {
            mockFetch.mockResolvedValue({
                status: 200,
                headers: { 'content-type': 'text/css' },
                text: jest.fn().mockResolvedValue(''),
            })

            const { page } = await createInterceptor()
            const handler = getRequestHandler(page.page)
            const req = mockRequest('stylesheet')

            handler(req)
            await new Promise(process.nextTick)

            const fetchHeaders = mockFetch.mock.calls[0][1].headers
            expect(fetchHeaders).not.toHaveProperty('host')
            expect(fetchHeaders).not.toHaveProperty('connection')
            expect(fetchHeaders).not.toHaveProperty('content-length')
            expect(fetchHeaders).toHaveProperty('accept', 'text/css')
        })

        it('defaults content-type to text/css when upstream omits it', async () => {
            mockFetch.mockResolvedValue({
                status: 200,
                headers: {},
                text: jest.fn().mockResolvedValue('h1 {}'),
            })

            const { page } = await createInterceptor()
            const handler = getRequestHandler(page.page)
            const req = mockRequest('stylesheet')

            handler(req)
            await new Promise(process.nextTick)

            expect(req.respond).toHaveBeenCalledWith(expect.objectContaining({ contentType: 'text/css' }))
        })

        it('responds with empty CSS on fetch failure', async () => {
            mockFetch.mockRejectedValue(new Error('ETIMEDOUT'))

            const { page } = await createInterceptor()
            const handler = getRequestHandler(page.page)
            const req = mockRequest('stylesheet')

            handler(req)
            await new Promise(process.nextTick)

            expect(req.respond).toHaveBeenCalledWith({
                status: 200,
                contentType: 'text/css',
                body: '',
            })
            expect(mockLog.warn).toHaveBeenCalledWith(
                expect.objectContaining({ err: 'ETIMEDOUT' }),
                'stylesheet proxy failed, responding empty'
            )
        })

        it('removes request from tracked when fallback respond also fails', async () => {
            mockFetch.mockRejectedValue(new Error('ETIMEDOUT'))

            const mp = mockPage()
            const bp = mockBlockProxy()
            const cp = mockCapturePage(mp.page)
            const interceptor = new RequestInterceptor(cp, bp, mockLog)
            await interceptor.install()

            const handler = getRequestHandler(mp.page)
            const req = mockRequest('stylesheet')
            ;(req.respond as jest.Mock).mockRejectedValue(new Error('Target closed'))

            handler(req)
            await new Promise(process.nextTick)

            // waitForSettled should resolve immediately — request was removed from tracked
            await expect(interceptor.waitForSettled()).resolves.toBeUndefined()
        })
    })

    describe('waitForSettled', () => {
        it('resolves immediately when no requests are pending', async () => {
            const { interceptor } = await createInterceptor()
            await expect(interceptor.waitForSettled()).resolves.toBeUndefined()
        })

        it('waits for tracked stylesheet requests to complete', async () => {
            mockFetch.mockImplementation(
                () =>
                    new Promise((resolve) =>
                        setTimeout(() => resolve({ status: 200, headers: {}, text: () => Promise.resolve('') }), 50)
                    )
            )

            const mp = mockPage()
            const bp = mockBlockProxy()
            const cp = mockCapturePage(mp.page)
            const interceptor = new RequestInterceptor(cp, bp, mockLog)
            await interceptor.install()

            const handler = getRequestHandler(mp.page)
            const req = mockRequest('stylesheet')
            handler(req)

            let settled = false
            const settledPromise = interceptor.waitForSettled().then(() => {
                settled = true
            })

            expect(settled).toBe(false)

            mp.emitRequestFinished(req)

            await settledPromise
            expect(settled).toBe(true)
        })

        it('resolves when the last of multiple stylesheet requests finishes', async () => {
            mockFetch.mockResolvedValue({
                status: 200,
                headers: {},
                text: jest.fn().mockResolvedValue(''),
            })

            const mp = mockPage()
            const bp = mockBlockProxy()
            const cp = mockCapturePage(mp.page)
            const interceptor = new RequestInterceptor(cp, bp, mockLog)
            await interceptor.install()

            const handler = getRequestHandler(mp.page)
            const req1 = mockRequest('stylesheet', subFrame, 'https://example.com/a.css')
            const req2 = mockRequest('stylesheet', subFrame, 'https://example.com/b.css')

            handler(req1)
            handler(req2)

            let settled = false
            const settledPromise = interceptor.waitForSettled().then(() => {
                settled = true
            })

            mp.emitRequestFinished(req1)
            await new Promise(process.nextTick)
            expect(settled).toBe(false)

            mp.emitRequestFinished(req2)
            await settledPromise
            expect(settled).toBe(true)
        })

        it('resolves when a tracked request fails', async () => {
            mockFetch.mockResolvedValue({
                status: 200,
                headers: {},
                text: jest.fn().mockResolvedValue(''),
            })

            const mp = mockPage()
            const bp = mockBlockProxy()
            const cp = mockCapturePage(mp.page)
            const interceptor = new RequestInterceptor(cp, bp, mockLog)
            await interceptor.install()

            const handler = getRequestHandler(mp.page)
            const req = mockRequest('stylesheet')
            handler(req)

            let settled = false
            const settledPromise = interceptor.waitForSettled().then(() => {
                settled = true
            })

            mp.emitRequestFailed(req)

            await settledPromise
            expect(settled).toBe(true)
        })

        it('does not track non-stylesheet requests', async () => {
            const { interceptor, page } = await createInterceptor()
            const handler = getRequestHandler(page.page)

            handler(mockRequest('image'))
            handler(mockRequest('font'))
            handler(mockRequest('media'))

            await expect(interceptor.waitForSettled()).resolves.toBeUndefined()
        })
    })
})
