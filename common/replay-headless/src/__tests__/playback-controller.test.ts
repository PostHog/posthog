import type { RecordingSegment } from '@posthog/replay-shared'

import type { HostBridge } from '../host-bridge'
import { PlaybackController } from '../playback-controller'

function makeSegment(
    overrides: Partial<RecordingSegment> & Pick<RecordingSegment, 'startTimestamp' | 'endTimestamp'>
): RecordingSegment {
    return {
        kind: 'window',
        durationMs: overrides.endTimestamp - overrides.startTimestamp,
        isActive: true,
        ...overrides,
    }
}

function mockBridge(): HostBridge {
    return { signalEnded: jest.fn() } as unknown as HostBridge
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
function mockReplayer() {
    const listeners: Record<string, Function[]> = {}
    return {
        on: jest.fn((event: string, cb: Function) => {
            ;(listeners[event] ||= []).push(cb)
        }),
        play: jest.fn(),
        pause: jest.fn(),
        getCurrentTime: jest.fn(() => 0),
        _emit: (event: string, data?: any) => {
            for (const cb of listeners[event] || []) {
                cb(data)
            }
        },
        iframe: { width: '1920', height: '1080' },
    }
}

describe('PlaybackController', () => {
    describe('lifecycle', () => {
        it('starts not stopped', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(replayer as any, [], 0, {}, bridge)
            expect(controller.isStopped).toBe(false)
        })

        it('signals ended on stop()', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(replayer as any, [], 0, {}, bridge)

            controller.stop()

            expect(controller.isStopped).toBe(true)
            expect(bridge.signalEnded).toHaveBeenCalledTimes(1)
        })

        it('stop() is idempotent', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(replayer as any, [], 0, {}, bridge)

            controller.stop()
            controller.stop()

            expect(controller.isStopped).toBe(true)
            expect(bridge.signalEnded).toHaveBeenCalledTimes(1)
        })

        it('calls replayer.play with startOffset on start()', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(replayer as any, [], 0, {}, bridge)

            controller.start(5000)

            expect(replayer.play).toHaveBeenCalledWith(5000)
        })
    })

    describe('finish event', () => {
        it('stops when replayer emits finish', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const _controller = new PlaybackController(replayer as any, [], 0, {}, bridge)

            replayer._emit('finish')

            expect(_controller.isStopped).toBe(true)
            expect(bridge.signalEnded).toHaveBeenCalledTimes(1)
        })
    })

    describe('endTimestamp cutoff', () => {
        it('stops and pauses when event timestamp reaches endTimestamp', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const _controller = new PlaybackController(
                replayer as any,
                [],
                1000,
                {
                    endTimestamp: 5000,
                },
                bridge
            )

            // Event before cutoff — no stop
            replayer._emit('event-cast', { timestamp: 4000 })
            expect(_controller.isStopped).toBe(false)

            // Event at cutoff — stop
            replayer._emit('event-cast', { timestamp: 5000 })
            expect(_controller.isStopped).toBe(true)
            expect(replayer.pause).toHaveBeenCalled()
        })

        it('does not register event-cast listener when no endTimestamp', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            new PlaybackController(replayer as any, [], 0, {}, bridge)

            const eventCastCalls = replayer.on.mock.calls.filter((c: any[]) => c[0] === 'event-cast')
            expect(eventCastCalls).toHaveLength(0)
        })
    })

    describe('inactivity skipping', () => {
        it('does not start skip loop without skipInactivity option', () => {
            const rafSpy = jest.spyOn(window, 'requestAnimationFrame')
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(replayer as any, [], 0, {}, bridge)

            controller.start(0)

            expect(rafSpy).not.toHaveBeenCalled()
            rafSpy.mockRestore()
        })

        it('starts rAF loop when skipInactivity is true', () => {
            const rafSpy = jest.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 0)
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const segments = [
                makeSegment({ startTimestamp: 1000, endTimestamp: 5000, isActive: true }),
                makeSegment({ startTimestamp: 5000, endTimestamp: 10000, isActive: false, kind: 'gap' }),
            ]
            const controller = new PlaybackController(
                replayer as any,
                segments,
                1000,
                {
                    skipInactivity: true,
                },
                bridge
            )

            controller.start(0)

            expect(rafSpy).toHaveBeenCalled()
            rafSpy.mockRestore()
        })

        it('skips to end of inactive segment when current time is in one', () => {
            let rafCallback: FrameRequestCallback | null = null
            jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
                rafCallback = cb
                return 0
            })

            const replayer = mockReplayer()
            const bridge = mockBridge()
            const segments = [
                makeSegment({ startTimestamp: 1000, endTimestamp: 5000, isActive: true }),
                makeSegment({ startTimestamp: 5000, endTimestamp: 10000, isActive: false, kind: 'gap' }),
                makeSegment({ startTimestamp: 10000, endTimestamp: 15000, isActive: true }),
            ]

            replayer.getCurrentTime.mockReturnValue(6000)

            const controller = new PlaybackController(
                replayer as any,
                segments,
                1000,
                {
                    skipInactivity: true,
                },
                bridge
            )
            controller.start(0)

            expect(rafCallback).toBeTruthy()
            rafCallback!(0)

            // Should skip to end of inactive segment (10000 - 1000 = 9000 offset)
            expect(replayer.play).toHaveBeenCalledWith(9000)

            jest.restoreAllMocks()
        })

        it('does not skip when stopped', () => {
            let rafCallback: FrameRequestCallback | null = null
            jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
                rafCallback = cb
                return 0
            })

            const replayer = mockReplayer()
            const bridge = mockBridge()
            const segments = [makeSegment({ startTimestamp: 1000, endTimestamp: 5000, isActive: false, kind: 'gap' })]
            replayer.getCurrentTime.mockReturnValue(2000)

            const controller = new PlaybackController(
                replayer as any,
                segments,
                1000,
                {
                    skipInactivity: true,
                },
                bridge
            )
            controller.start(0)
            controller.stop()

            replayer.play.mockClear()

            rafCallback!(0)

            expect(replayer.play).not.toHaveBeenCalled()

            jest.restoreAllMocks()
        })
    })
})
