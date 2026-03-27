import type { PlayerConfig, PlayerMessage } from '@posthog/replay-headless/protocol'
import { PLAYER_CONFIG_KEY, PLAYER_EMIT_FN, PLAYER_START_EVENT } from '@posthog/replay-headless/protocol'

import { PlayerController } from '../capture/player'
import { RasterizationError } from '../errors'

const flushPromises = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

const mockInternalFetch = jest.fn()
jest.mock('../../../utils/request', () => ({
    internalFetch: (...args: any[]) => mockInternalFetch(...args),
}))

jest.mock('../logger', () => ({
    createLogger: () => ({
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
        debug: jest.fn(),
        child: jest.fn().mockReturnThis(),
    }),
}))

function mockPage() {
    let emitFn: ((msg: PlayerMessage) => void) | null = null
    let _evaluateOnNewDocumentFn: ((...args: any[]) => void) | null = null
    const requestHandlers: Array<(req: any) => void> = []

    return {
        exposeFunction: jest.fn().mockImplementation((name: string, fn: any) => {
            if (name === PLAYER_EMIT_FN) {
                emitFn = fn
            }
            return Promise.resolve()
        }),
        evaluateOnNewDocument: jest.fn().mockImplementation((fn: any) => {
            _evaluateOnNewDocumentFn = fn
            return Promise.resolve()
        }),
        setRequestInterception: jest.fn().mockResolvedValue(undefined),
        on: jest.fn().mockImplementation((event: string, handler: any) => {
            if (event === 'request') {
                requestHandlers.push(handler)
            }
        }),
        goto: jest.fn().mockResolvedValue(undefined),
        evaluate: jest.fn().mockResolvedValue(undefined),

        // Test helpers
        _emit(msg: PlayerMessage) {
            emitFn?.(msg)
        },
        _getRequestHandlers() {
            return requestHandlers
        },
    }
}

const testCfg = {
    siteUrl: 'http://localhost:8000',
    recordingApiBaseUrl: 'http://localhost:6738',
    recordingApiSecret: 'secret',
}

function basePlayerConfig(overrides: Partial<PlayerConfig> = {}): PlayerConfig {
    return {
        teamId: 1,
        sessionId: 'test-session',
        playbackSpeed: 4,
        blockCount: 0,
        skipInactivity: true,
        mouseTail: true,
        viewportEvents: [],
        ...overrides,
    }
}

describe('PlayerController', () => {
    it('load() sets up exposeFunction, evaluateOnNewDocument, request interception, and navigates', async () => {
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html></html>', testCfg)

        await controller.load(basePlayerConfig(), [])

        expect(page.exposeFunction).toHaveBeenCalledWith(PLAYER_EMIT_FN, expect.any(Function))
        expect(page.evaluateOnNewDocument).toHaveBeenCalledWith(
            expect.any(Function),
            PLAYER_CONFIG_KEY,
            expect.objectContaining({ sessionId: 'test-session' })
        )
        expect(page.setRequestInterception).toHaveBeenCalledWith(true)
        expect(page.goto).toHaveBeenCalledWith('http://localhost:8000/player', {
            waitUntil: 'load',
            timeout: 30000,
        })
    })

    it('load() intercepts player URL and passes through other requests', async () => {
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html>player</html>', testCfg)

        await controller.load(basePlayerConfig(), [])

        const handlers = page._getRequestHandlers()
        expect(handlers).toHaveLength(1)

        const playerRequest = {
            url: () => 'http://localhost:8000/player',
            respond: jest.fn().mockResolvedValue(undefined),
            continue: jest.fn().mockResolvedValue(undefined),
        }
        handlers[0](playerRequest)
        expect(playerRequest.respond).toHaveBeenCalledWith({
            status: 200,
            contentType: 'text/html',
            body: '<html>player</html>',
        })

        const otherRequest = {
            url: () => 'https://cdn.example.com/font.woff2',
            respond: jest.fn(),
            continue: jest.fn().mockResolvedValue(undefined),
            headers: jest.fn().mockReturnValue({}),
        }
        handlers[0](otherRequest)
        expect(otherRequest.continue).toHaveBeenCalled()
        expect(otherRequest.respond).not.toHaveBeenCalled()
    })

    it('waitForStart() resolves when player sends started message', async () => {
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html></html>', testCfg)
        await controller.load(basePlayerConfig(), [])

        const startPromise = controller.waitForStart(basePlayerConfig(), 5000)

        // Simulate player sending started
        page._emit({ type: 'started' })

        await expect(startPromise).resolves.toBeUndefined()
    })

    it('waitForStart() resets timeout on loading_progress messages', async () => {
        jest.useFakeTimers()
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html></html>', testCfg)
        await controller.load(basePlayerConfig(), [])

        const startPromise = controller.waitForStart(basePlayerConfig(), 1000)

        // Advance 800ms — almost at timeout
        jest.advanceTimersByTime(800)
        // Progress resets the timer
        page._emit({ type: 'loading_progress', loaded: 1, total: 5 })

        // Advance another 800ms — would have timed out without reset
        jest.advanceTimersByTime(800)
        // Still alive — send started
        page._emit({ type: 'started' })

        await expect(startPromise).resolves.toBeUndefined()
        jest.useRealTimers()
    })

    it('waitForStart() rejects on timeout when no progress', async () => {
        jest.useFakeTimers()
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html></html>', testCfg)
        await controller.load(basePlayerConfig(), [])

        const startPromise = controller.waitForStart(basePlayerConfig({ sessionId: 'sess-abc' }), 1000)

        jest.advanceTimersByTime(1001)

        await expect(startPromise).rejects.toThrow('Recording did not start for session sess-abc')
        await expect(startPromise).rejects.toBeInstanceOf(RasterizationError)
        jest.useRealTimers()
    })

    it('waitForStart() rejects when player sends error message', async () => {
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html></html>', testCfg)
        await controller.load(basePlayerConfig(), [])

        const startPromise = controller.waitForStart(basePlayerConfig(), 5000)

        page._emit({
            type: 'error',
            code: 'NO_SNAPSHOTS',
            message: 'No snapshot data found',
            retryable: false,
        })

        await expect(startPromise).rejects.toThrow('[NO_SNAPSHOTS] No snapshot data found')
        await expect(startPromise).rejects.toBeInstanceOf(RasterizationError)
    })

    it('isEnded() returns true after ended message', async () => {
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html></html>', testCfg)
        await controller.load(basePlayerConfig(), [])

        expect(controller.isEnded()).toBe(false)
        page._emit({ type: 'ended' })
        expect(controller.isEnded()).toBe(true)
    })

    it('getError() returns stored error from message received outside active promise', async () => {
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html></html>', testCfg)
        await controller.load(basePlayerConfig(), [])

        expect(controller.getError()).toBeNull()

        // Error arrives when no promise is waiting (e.g. during capture loop)
        page._emit({
            type: 'error',
            code: 'PLAYBACK_ERROR',
            message: 'rendering failed',
            retryable: true,
        })

        const err = controller.getError()
        expect(err).toBeInstanceOf(RasterizationError)
        expect(err!.message).toBe('[PLAYBACK_ERROR] rendering failed')
        expect(err!.code).toBe('PLAYBACK_ERROR')
        expect(err!.retryable).toBe(true)
    })

    it('getInactivityPeriods() returns periods from player', async () => {
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html></html>', testCfg)
        await controller.load(basePlayerConfig(), [])

        expect(controller.getInactivityPeriods()).toEqual([])

        const periods = [
            { ts_from_s: 0, ts_to_s: 5, active: true },
            { ts_from_s: 5, ts_to_s: 15, active: false },
        ]
        page._emit({ type: 'inactivity_periods', periods })

        expect(controller.getInactivityPeriods()).toEqual(periods)
    })

    it('startPlayback() dispatches the start event', async () => {
        const page = mockPage()
        const controller = new PlayerController(page as any, '<html></html>', testCfg)
        await controller.load(basePlayerConfig(), [])

        await controller.startPlayback()

        expect(page.evaluate).toHaveBeenCalledWith(expect.any(Function), PLAYER_START_EVENT)
    })

    describe('handleBlockRequest (via request interception)', () => {
        const blocks = [
            { key: 'recordings/block-0', start_byte: 0, end_byte: 1000 },
            { key: 'recordings/block-1', start_byte: 100, end_byte: 2000 },
        ]

        function mockBlockRequest(path: string) {
            return {
                url: () => `http://localhost:8000${path}`,
                respond: jest.fn().mockResolvedValue(undefined),
                continue: jest.fn(),
            }
        }

        afterEach(() => {
            jest.restoreAllMocks()
            mockInternalFetch.mockReset()
        })

        it('proxies valid block index to recording-api with auth header', async () => {
            mockInternalFetch.mockResolvedValue({
                status: 200,
                headers: { 'content-type': 'application/jsonl' },
                text: jest.fn().mockResolvedValue('{"data":"test"}'),
            })

            const page = mockPage()
            const config = basePlayerConfig({ blockCount: 2 })
            const controller = new PlayerController(page as any, '<html></html>', testCfg)
            await controller.load(config, blocks)

            const handlers = page._getRequestHandlers()
            const blockRequest = mockBlockRequest('/__blocks/0')
            handlers[0](blockRequest)
            await flushPromises()

            expect(mockInternalFetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/projects/1/recordings/test-session/block?'),
                { headers: { 'X-Internal-Api-Secret': 'secret' } }
            )
            const fetchUrl = mockInternalFetch.mock.calls[0][0] as string
            expect(fetchUrl).toContain('key=recordings%2Fblock-0')
            expect(fetchUrl).toContain('start_byte=0')
            expect(fetchUrl).toContain('end_byte=1000')
            expect(fetchUrl).toContain('decompress=true')
            expect(blockRequest.respond).toHaveBeenCalledWith(
                expect.objectContaining({ status: 200, contentType: 'application/jsonl' })
            )
        })

        it('returns 404 for out-of-range index', async () => {
            const page = mockPage()
            const controller = new PlayerController(page as any, '<html></html>', testCfg)
            await controller.load(basePlayerConfig({ blockCount: 2 }), blocks)

            const handlers = page._getRequestHandlers()
            const blockRequest = mockBlockRequest('/__blocks/5')
            handlers[0](blockRequest)
            await flushPromises()

            expect(blockRequest.respond).toHaveBeenCalledWith({ status: 404, body: 'block not found' })
        })

        it('returns 404 for NaN index', async () => {
            const page = mockPage()
            const controller = new PlayerController(page as any, '<html></html>', testCfg)
            await controller.load(basePlayerConfig({ blockCount: 2 }), blocks)

            const handlers = page._getRequestHandlers()
            const blockRequest = mockBlockRequest('/__blocks/abc')
            handlers[0](blockRequest)
            await flushPromises()

            expect(blockRequest.respond).toHaveBeenCalledWith({ status: 404, body: 'block not found' })
        })

        it('forwards upstream non-ok status', async () => {
            mockInternalFetch.mockResolvedValue({
                status: 500,
                text: jest.fn().mockResolvedValue('internal error'),
            })

            const page = mockPage()
            const controller = new PlayerController(page as any, '<html></html>', testCfg)
            await controller.load(basePlayerConfig({ blockCount: 2 }), blocks)

            const handlers = page._getRequestHandlers()
            const blockRequest = mockBlockRequest('/__blocks/0')
            handlers[0](blockRequest)
            await flushPromises()

            expect(blockRequest.respond).toHaveBeenCalledWith({ status: 500, body: 'internal error' })
        })

        it('returns 502 when upstream fetch throws', async () => {
            mockInternalFetch.mockRejectedValue(new Error('network timeout'))

            const page = mockPage()
            const controller = new PlayerController(page as any, '<html></html>', testCfg)
            await controller.load(basePlayerConfig({ blockCount: 2 }), blocks)

            const handlers = page._getRequestHandlers()
            const blockRequest = mockBlockRequest('/__blocks/0')
            handlers[0](blockRequest)
            await flushPromises()

            expect(blockRequest.respond).toHaveBeenCalledWith({ status: 502, body: 'block proxy error' })
        })
    })
})
