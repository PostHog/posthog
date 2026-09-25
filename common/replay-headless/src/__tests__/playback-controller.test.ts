import type { RecordingSegment } from '@posthog/replay-shared'

import type { HostBridge } from '../host-bridge'
import { PlaybackController, type PlaybackWindow } from '../playback-controller'

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
    return { signalEnded: jest.fn(), publishFrameTimeline: jest.fn() } as unknown as HostBridge
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

function oneWindow(replayer: ReturnType<typeof mockReplayer>, firstTimestamp: number): PlaybackWindow[] {
    return [{ windowId: 1, replayer: replayer as any, firstTimestamp, lastTimestamp: Number.MAX_SAFE_INTEGER }]
}

describe('PlaybackController', () => {
    describe('lifecycle', () => {
        it('starts not stopped', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(oneWindow(replayer, 0), [], 0, {}, bridge)
            expect(controller.isStopped).toBe(false)
        })

        it('signals ended on stop()', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(oneWindow(replayer, 0), [], 0, {}, bridge)

            controller.stop()

            expect(controller.isStopped).toBe(true)
            expect(bridge.signalEnded).toHaveBeenCalledTimes(1)
        })

        it('stop() is idempotent', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(oneWindow(replayer, 0), [], 0, {}, bridge)

            controller.stop()
            controller.stop()

            expect(controller.isStopped).toBe(true)
            expect(bridge.signalEnded).toHaveBeenCalledTimes(1)
        })

        it('calls replayer.play with startOffset on start()', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(oneWindow(replayer, 0), [], 0, {}, bridge)

            controller.start(5000)

            expect(replayer.play).toHaveBeenCalledWith(5000)
        })
    })

    describe('finish event', () => {
        it('stops when replayer emits finish', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const _controller = new PlaybackController(oneWindow(replayer, 0), [], 0, {}, bridge)

            replayer._emit('finish')

            expect(_controller.isStopped).toBe(true)
            expect(bridge.signalEnded).toHaveBeenCalledTimes(1)
        })
    })

    describe('endOffsetS cutoff', () => {
        it('stops and pauses when event timestamp reaches end offset', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            // firstTimestamp=1000, endOffsetS=4 → absolute cutoff at 1000 + 4*1000 = 5000
            const _controller = new PlaybackController(
                oneWindow(replayer, 1000),
                [],
                1000,
                {
                    endOffsetS: 4,
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

        it('does not register event-cast listener when no endOffsetS', () => {
            const replayer = mockReplayer()
            const bridge = mockBridge()
            new PlaybackController(oneWindow(replayer, 0), [], 0, {}, bridge)

            const eventCastCalls = replayer.on.mock.calls.filter((c: any[]) => c[0] === 'event-cast')
            expect(eventCastCalls).toHaveLength(0)
        })
    })

    describe('inactivity skipping', () => {
        it('records frames but skips nothing without skipInactivity option', () => {
            // The loop runs either way: the frame timeline is what maps video positions back to the
            // recording clock, and it is needed whether or not anything gets skipped.
            const rafSpy = jest.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 0)
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const segments = [makeSegment({ startTimestamp: 0, endTimestamp: 5000, isActive: false, kind: 'gap' })]
            const controller = new PlaybackController(oneWindow(replayer, 0), segments, 0, {}, bridge)

            controller.start(0)
            rafSpy.mock.calls[0][0](0)

            expect(rafSpy).toHaveBeenCalled()
            expect(replayer.play).toHaveBeenCalledTimes(1)
            expect(controller.getFrameSessionMs()).toHaveLength(1)
            rafSpy.mockRestore()
        })

        it('publishes the frame timeline when playback stops', () => {
            const rafSpy = jest.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 0)
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const controller = new PlaybackController(oneWindow(replayer, 0), [], 0, {}, bridge)

            controller.start(0)
            rafSpy.mock.calls[0][0](0)
            controller.stop()

            expect(bridge.publishFrameTimeline).toHaveBeenCalledWith([0])
            rafSpy.mockRestore()
        })

        it('starts rAF loop when skipInactivity is true', () => {
            const rafSpy = jest.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 0)
            const replayer = mockReplayer()
            const bridge = mockBridge()
            const segments = [
                makeSegment({
                    startTimestamp: 1000,
                    endTimestamp: 5000,
                    isActive: true,
                }),
                makeSegment({
                    startTimestamp: 5000,
                    endTimestamp: 10000,
                    isActive: false,
                    kind: 'gap',
                }),
            ]
            const controller = new PlaybackController(
                oneWindow(replayer, 1000),
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
                makeSegment({
                    startTimestamp: 1000,
                    endTimestamp: 5000,
                    isActive: true,
                }),
                makeSegment({
                    startTimestamp: 5000,
                    endTimestamp: 10000,
                    isActive: false,
                    kind: 'gap',
                }),
                makeSegment({
                    startTimestamp: 10000,
                    endTimestamp: 15000,
                    isActive: true,
                }),
            ]

            replayer.getCurrentTime.mockReturnValue(6000)

            const controller = new PlaybackController(
                oneWindow(replayer, 1000),
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
            const segments = [
                makeSegment({
                    startTimestamp: 1000,
                    endTimestamp: 5000,
                    isActive: false,
                    kind: 'gap',
                }),
            ]
            replayer.getCurrentTime.mockReturnValue(2000)

            const controller = new PlaybackController(
                oneWindow(replayer, 1000),
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

    describe('multiple windows', () => {
        function twoWindows(): {
            a: ReturnType<typeof mockReplayer>
            b: ReturnType<typeof mockReplayer>
            windows: PlaybackWindow[]
            segments: RecordingSegment[]
        } {
            const a = mockReplayer()
            const b = mockReplayer()
            return {
                a,
                b,
                windows: [
                    { windowId: 1, replayer: a as any, firstTimestamp: 1000, lastTimestamp: 5000 },
                    { windowId: 2, replayer: b as any, firstTimestamp: 3000, lastTimestamp: 9000 },
                ],
                segments: [
                    makeSegment({ startTimestamp: 1000, endTimestamp: 5000, windowId: 1 }),
                    makeSegment({ startTimestamp: 5000, endTimestamp: 9000, windowId: 2 }),
                ],
            }
        }

        it('hands playback to the window that owns the next segment', () => {
            let rafCallback: FrameRequestCallback | null = null
            jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
                rafCallback = cb
                return 0
            })
            const { a, b, windows, segments } = twoWindows()
            const controller = new PlaybackController(windows, segments, 1000, {}, mockBridge())
            const shown: number[] = []
            controller.onWindowChange((tab) => shown.push(tab.windowId))

            controller.start(0)
            a.getCurrentTime.mockReturnValue(4500)
            rafCallback!(0)

            expect(a.pause).toHaveBeenCalled()
            expect(b.play).toHaveBeenCalledWith(2500)
            expect(shown).toEqual([1, 2])
            expect(controller.getFrameSessionMs()).toEqual([4500])

            jest.restoreAllMocks()
        })

        it('starts in the window that owns the start offset', () => {
            jest.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 0)
            const { a, b, windows, segments } = twoWindows()
            const controller = new PlaybackController(windows, segments, 1000, {}, mockBridge())

            controller.start(6000)

            expect(controller.activeWindow.windowId).toBe(2)
            expect(b.play).toHaveBeenCalledWith(4000)
            expect(a.play).not.toHaveBeenCalled()

            jest.restoreAllMocks()
        })

        it('switches windows when an inactivity skip lands in another window', () => {
            let rafCallback: FrameRequestCallback | null = null
            jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
                rafCallback = cb
                return 0
            })
            const { a, b, windows } = twoWindows()
            const segments = [
                makeSegment({ startTimestamp: 1000, endTimestamp: 3000, windowId: 1 }),
                makeSegment({ startTimestamp: 3000, endTimestamp: 6000, windowId: 1, isActive: false, kind: 'gap' }),
                makeSegment({ startTimestamp: 6000, endTimestamp: 9000, windowId: 2 }),
            ]
            const controller = new PlaybackController(windows, segments, 1000, { skipInactivity: true }, mockBridge())

            controller.start(0)
            a.getCurrentTime.mockReturnValue(2500)
            rafCallback!(0)

            expect(controller.activeWindow.windowId).toBe(2)
            expect(b.play).toHaveBeenCalledWith(3000)

            jest.restoreAllMocks()
        })

        it('continues in another window when the one on screen runs out of events', () => {
            const { a, b, windows, segments } = twoWindows()
            const bridge = mockBridge()
            const controller = new PlaybackController(windows, segments, 1000, {}, bridge)

            a.getCurrentTime.mockReturnValue(3000)
            a._emit('finish')

            expect(controller.isStopped).toBe(false)
            expect(controller.activeWindow.windowId).toBe(2)
            expect(b.play).toHaveBeenCalledWith(2000)
        })
    })
})
