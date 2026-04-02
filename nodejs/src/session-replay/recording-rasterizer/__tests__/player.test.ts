import type { PlayerConfig, PlayerMessage } from '@posthog/replay-headless/protocol'
import { PLAYER_CONFIG_KEY, PLAYER_EMIT_FN, PLAYER_START_EVENT } from '@posthog/replay-headless/protocol'

import { BlockProxy } from '../capture/block-proxy'
import { CapturePage } from '../capture/capture-page'
import { PlayerController } from '../capture/player'
import { RasterizationError } from '../errors'

jest.mock('../capture/request-interceptor', () => ({
    RequestInterceptor: jest.fn().mockImplementation(() => ({
        install: jest.fn().mockResolvedValue(undefined),
        waitForSettled: jest.fn().mockResolvedValue(undefined),
    })),
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

const playerUrl = 'http://localhost:8000/player'
const playerHtml = '<html>player</html>'

function mockCapturePage() {
    let emitFn: ((msg: PlayerMessage) => void) | null = null

    const page = {
        exposeFunction: jest.fn().mockImplementation((name: string, fn: any) => {
            if (name === PLAYER_EMIT_FN) {
                emitFn = fn
            }
            return Promise.resolve()
        }),
        evaluateOnNewDocument: jest.fn().mockResolvedValue(undefined),
        goto: jest.fn().mockResolvedValue(undefined),
        evaluate: jest.fn().mockResolvedValue(undefined),
    }

    const capturePage = { page, playerUrl, playerHtml } as unknown as CapturePage

    return {
        capturePage,
        page,
        _emit(msg: PlayerMessage) {
            emitFn?.(msg)
        },
    }
}

const mockBlockProxy = {} as unknown as BlockProxy

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
    it('load() sets up exposeFunction, evaluateOnNewDocument, and navigates', async () => {
        const { capturePage, page } = mockCapturePage()
        const controller = new PlayerController(capturePage, mockBlockProxy)

        await controller.load(basePlayerConfig())

        expect(page.exposeFunction).toHaveBeenCalledWith(PLAYER_EMIT_FN, expect.any(Function))
        expect(page.evaluateOnNewDocument).toHaveBeenCalledWith(
            expect.any(Function),
            PLAYER_CONFIG_KEY,
            expect.objectContaining({ sessionId: 'test-session' })
        )
        expect(page.goto).toHaveBeenCalledWith(playerUrl, {
            waitUntil: 'load',
            timeout: 30000,
        })
    })

    it('waitForStart() resolves when player sends started message', async () => {
        const mp = mockCapturePage()
        const controller = new PlayerController(mp.capturePage, mockBlockProxy)
        await controller.load(basePlayerConfig())

        const startPromise = controller.waitForStart(basePlayerConfig(), 5000)

        mp._emit({ type: 'started' })

        await expect(startPromise).resolves.toBeUndefined()
    })

    it('waitForStart() resets timeout on loading_progress messages', async () => {
        jest.useFakeTimers()
        const mp = mockCapturePage()
        const controller = new PlayerController(mp.capturePage, mockBlockProxy)
        await controller.load(basePlayerConfig())

        const startPromise = controller.waitForStart(basePlayerConfig(), 1000)

        // Advance 800ms — almost at timeout
        jest.advanceTimersByTime(800)
        // Progress resets the timer
        mp._emit({ type: 'loading_progress', loaded: 1, total: 5 })

        // Advance another 800ms — would have timed out without reset
        jest.advanceTimersByTime(800)
        // Still alive — send started
        mp._emit({ type: 'started' })

        await expect(startPromise).resolves.toBeUndefined()
        jest.useRealTimers()
    })

    it('waitForStart() rejects on timeout when no progress', async () => {
        jest.useFakeTimers()
        const mp = mockCapturePage()
        const controller = new PlayerController(mp.capturePage, mockBlockProxy)
        await controller.load(basePlayerConfig())

        const startPromise = controller.waitForStart(basePlayerConfig({ sessionId: 'sess-abc' }), 1000)

        jest.advanceTimersByTime(1001)

        await expect(startPromise).rejects.toThrow('Recording did not start for session sess-abc')
        await expect(startPromise).rejects.toBeInstanceOf(RasterizationError)
        jest.useRealTimers()
    })

    it('waitForStart() rejects when player sends error message', async () => {
        const mp = mockCapturePage()
        const controller = new PlayerController(mp.capturePage, mockBlockProxy)
        await controller.load(basePlayerConfig())

        const startPromise = controller.waitForStart(basePlayerConfig(), 5000)

        mp._emit({
            type: 'error',
            code: 'NO_SNAPSHOTS',
            message: 'No snapshot data found',
            retryable: false,
        })

        await expect(startPromise).rejects.toThrow('[NO_SNAPSHOTS] No snapshot data found')
        await expect(startPromise).rejects.toBeInstanceOf(RasterizationError)
    })

    it('isEnded() returns true after ended message', async () => {
        const mp = mockCapturePage()
        const controller = new PlayerController(mp.capturePage, mockBlockProxy)
        await controller.load(basePlayerConfig())

        expect(controller.isEnded()).toBe(false)
        mp._emit({ type: 'ended' })
        expect(controller.isEnded()).toBe(true)
    })

    it('getError() returns stored error from message received outside active promise', async () => {
        const mp = mockCapturePage()
        const controller = new PlayerController(mp.capturePage, mockBlockProxy)
        await controller.load(basePlayerConfig())

        expect(controller.getError()).toBeNull()

        mp._emit({
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
        const mp = mockCapturePage()
        const controller = new PlayerController(mp.capturePage, mockBlockProxy)
        await controller.load(basePlayerConfig())

        expect(controller.getInactivityPeriods()).toEqual([])

        const periods = [
            { ts_from_s: 0, ts_to_s: 5, active: true },
            { ts_from_s: 5, ts_to_s: 15, active: false },
        ]
        mp._emit({ type: 'inactivity_periods', periods })

        expect(controller.getInactivityPeriods()).toEqual(periods)
    })

    it('startPlayback() dispatches the start event', async () => {
        const { capturePage, page } = mockCapturePage()
        const controller = new PlayerController(capturePage, mockBlockProxy)
        await controller.load(basePlayerConfig())

        await controller.startPlayback()

        expect(page.evaluate).toHaveBeenCalledWith(expect.any(Function), PLAYER_START_EVENT)
    })
})
