import { Frame, HTTPRequest, Page } from 'puppeteer'

import { AssetProxy } from '../capture/asset-proxy'

const mockFetch = jest.fn()
jest.mock('../../../utils/request', () => ({
    fetch: (...args: any[]) => mockFetch(...args),
}))

type PageEventHandler = (req: HTTPRequest) => void

const mainFrame = { name: 'mainFrame' } as unknown as Frame
const subFrame = { name: 'subFrame' } as unknown as Frame

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
    } as unknown as Page

    return {
        page,
        emitRequestFinished: (req) => handlers['requestfinished']?.forEach((h) => h(req)),
        emitRequestFailed: (req) => handlers['requestfailed']?.forEach((h) => h(req)),
    }
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

describe('AssetProxy', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('request routing', () => {
        it('continues main-frame requests without proxying', () => {
            const { page } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req = mockRequest('stylesheet', mainFrame)

            proxy.handleRequest(req)

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

            const { page } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req = mockRequest('stylesheet')

            proxy.handleRequest(req)
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

        it('aborts sub-frame media requests immediately', () => {
            const { page } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req = mockRequest('media')

            proxy.handleRequest(req)
            expect(req.abort).toHaveBeenCalled()
            expect(req.respond).not.toHaveBeenCalled()
            expect(req.continue).not.toHaveBeenCalled()
        })

        it.each(['image', 'font', 'script', 'xhr', 'fetch', 'document'])(
            'continues sub-frame %s requests normally',
            (type) => {
                const { page } = mockPage()
                const proxy = new AssetProxy(page, mockLog)
                const req = mockRequest(type)

                proxy.handleRequest(req)
                expect(req.continue).toHaveBeenCalled()
                expect(req.abort).not.toHaveBeenCalled()
                expect(req.respond).not.toHaveBeenCalled()
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

            const { page } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req = mockRequest('stylesheet')

            proxy.handleRequest(req)
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

            const { page } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req = mockRequest('stylesheet')

            proxy.handleRequest(req)
            await new Promise(process.nextTick)

            expect(req.respond).toHaveBeenCalledWith(expect.objectContaining({ contentType: 'text/css' }))
        })

        it('responds with empty CSS on fetch failure', async () => {
            mockFetch.mockRejectedValue(new Error('ETIMEDOUT'))

            const { page } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req = mockRequest('stylesheet')

            proxy.handleRequest(req)
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

            const { page } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req = mockRequest('stylesheet')
            ;(req.respond as jest.Mock).mockRejectedValue(new Error('Target closed'))

            proxy.handleRequest(req)
            await new Promise(process.nextTick)

            // waitForSettled should resolve immediately — request was removed from tracked
            await expect(proxy.waitForSettled()).resolves.toBeUndefined()
        })
    })

    describe('waitForSettled', () => {
        it('resolves immediately when no requests are pending', async () => {
            const { page } = mockPage()
            const proxy = new AssetProxy(page, mockLog)

            await expect(proxy.waitForSettled()).resolves.toBeUndefined()
        })

        it('waits for tracked stylesheet requests to complete', async () => {
            mockFetch.mockImplementation(
                () =>
                    new Promise((resolve) =>
                        setTimeout(() => resolve({ status: 200, headers: {}, text: () => Promise.resolve('') }), 50)
                    )
            )

            const { page, emitRequestFinished } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req = mockRequest('stylesheet')

            proxy.handleRequest(req)

            let settled = false
            const settledPromise = proxy.waitForSettled().then(() => {
                settled = true
            })

            expect(settled).toBe(false)

            emitRequestFinished(req)

            await settledPromise
            expect(settled).toBe(true)
        })

        it('resolves when the last of multiple stylesheet requests finishes', async () => {
            mockFetch.mockResolvedValue({
                status: 200,
                headers: {},
                text: jest.fn().mockResolvedValue(''),
            })

            const { page, emitRequestFinished } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req1 = mockRequest('stylesheet', subFrame, 'https://example.com/a.css')
            const req2 = mockRequest('stylesheet', subFrame, 'https://example.com/b.css')

            proxy.handleRequest(req1)
            proxy.handleRequest(req2)

            let settled = false
            const settledPromise = proxy.waitForSettled().then(() => {
                settled = true
            })

            emitRequestFinished(req1)
            await new Promise(process.nextTick)
            expect(settled).toBe(false)

            emitRequestFinished(req2)
            await settledPromise
            expect(settled).toBe(true)
        })

        it('resolves when a tracked request fails', async () => {
            mockFetch.mockResolvedValue({
                status: 200,
                headers: {},
                text: jest.fn().mockResolvedValue(''),
            })

            const { page, emitRequestFailed } = mockPage()
            const proxy = new AssetProxy(page, mockLog)
            const req = mockRequest('stylesheet')

            proxy.handleRequest(req)

            let settled = false
            const settledPromise = proxy.waitForSettled().then(() => {
                settled = true
            })

            emitRequestFailed(req)

            await settledPromise
            expect(settled).toBe(true)
        })

        it('does not track non-stylesheet requests', async () => {
            const { page } = mockPage()
            const proxy = new AssetProxy(page, mockLog)

            proxy.handleRequest(mockRequest('image'))
            proxy.handleRequest(mockRequest('font'))
            proxy.handleRequest(mockRequest('media'))

            await expect(proxy.waitForSettled()).resolves.toBeUndefined()
        })
    })
})
