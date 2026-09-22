import {
    FrameState,
    initialFrameState,
    resolveFrameTimestamp,
    STUCK_TIME_THRESHOLD_MS,
} from './resolve-frame-timestamp'

const FPS_1X = 1 * (1000 / 60) // ~16.67ms

function state(lastProgressTimestamp: number | undefined, lastProgressAt: number | undefined): FrameState {
    return { lastProgressTimestamp, lastProgressAt }
}

describe('resolveFrameTimestamp', () => {
    describe('core behavior', () => {
        it.each([
            {
                name: 'normal playback — rrweb advances past the last high point, not stuck',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(900, 0),
                now: FPS_1X,
                expectedTs: 1000,
                expectedAdvance: false,
            },
            {
                name: 'jitter below the high point, within the stuck window',
                rrwebTs: 999,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(1000, 0),
                now: STUCK_TIME_THRESHOLD_MS - 1,
                expectedTs: 999,
                expectedAdvance: false,
            },
            {
                name: 'jitter below the high point, past the stuck window (manually advances)',
                rrwebTs: 999,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(1000, 0),
                now: STUCK_TIME_THRESHOLD_MS,
                expectedTs: 500 + FPS_1X,
                expectedAdvance: true,
            },
            {
                name: 'frozen on the same timestamp past the stuck window (manually advances)',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(1000, 0),
                now: STUCK_TIME_THRESHOLD_MS,
                expectedTs: 500 + FPS_1X,
                expectedAdvance: true,
            },
            {
                name: 'gap segment — undefined timestamp (immediately advances)',
                rrwebTs: undefined,
                currentTs: 500,
                segmentKind: 'gap' as const,
                prev: state(undefined, 0),
                now: 0,
                expectedTs: 500 + FPS_1X,
                expectedAdvance: true,
            },
            {
                name: 'gap segment — undefined timestamp, no currentTimestamp (cannot advance)',
                rrwebTs: undefined,
                currentTs: undefined,
                segmentKind: 'gap' as const,
                prev: state(undefined, 0),
                now: 0,
                expectedTs: undefined,
                expectedAdvance: true,
            },
            {
                name: 'window segment — undefined timestamp within the stuck window (bail out downstream)',
                rrwebTs: undefined,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(undefined, 0),
                now: STUCK_TIME_THRESHOLD_MS - 1,
                expectedTs: undefined,
                expectedAdvance: false,
            },
            {
                name: 'buffer segment — stuck past the window (advances, buffer check is downstream)',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'buffer' as const,
                prev: state(1000, 0),
                now: STUCK_TIME_THRESHOLD_MS,
                expectedTs: 500 + FPS_1X,
                expectedAdvance: true,
            },
        ])('$name', ({ rrwebTs, currentTs, segmentKind, prev, now, expectedTs, expectedAdvance }) => {
            const result = resolveFrameTimestamp(rrwebTs, currentTs, segmentKind, FPS_1X, prev, now)
            if (expectedTs === undefined) {
                expect(result.resolvedTimestamp).toBeUndefined()
            } else {
                expect(result.resolvedTimestamp).toBeCloseTo(expectedTs, 1)
            }
            expect(result.shouldManuallyAdvance).toBe(expectedAdvance)
        })
    })

    describe('multi-frame sequences', () => {
        it('normal playback — increasing timestamps never trigger stuck', () => {
            let frameState = initialFrameState()
            for (let i = 0; i < 20; i++) {
                const rrwebTs = 1000 + i * 17
                const result = resolveFrameTimestamp(rrwebTs, rrwebTs, 'window', FPS_1X, frameState, i * 17)
                expect(result.shouldManuallyAdvance).toBe(false)
                frameState = result.newState
            }
        })

        it('jitter without net progress — nudges once the stuck window elapses', () => {
            // The regression this guards: an rrweb clock that oscillates around a fixed point
            // changes value every frame but never advances, so a frame-count check never trips.
            let frameState = initialFrameState()
            const jitter = [5000, 4999, 5001, 4998, 5000, 4999]
            let advanced = false

            for (let frame = 0; frame < 200; frame++) {
                const rrwebTs = jitter[frame % jitter.length]
                const now = frame * FPS_1X
                const result = resolveFrameTimestamp(rrwebTs, 5000, 'window', FPS_1X, frameState, now)
                frameState = result.newState
                if (now < STUCK_TIME_THRESHOLD_MS) {
                    expect(result.shouldManuallyAdvance).toBe(false)
                } else if (result.shouldManuallyAdvance) {
                    advanced = true
                    break
                }
            }
            expect(advanced).toBe(true)
        })

        it('gap traversal — each frame advances by fps', () => {
            let frameState = initialFrameState()
            let currentTs = 10000

            for (let i = 0; i < 5; i++) {
                const result = resolveFrameTimestamp(undefined, currentTs, 'gap', FPS_1X, frameState, i * FPS_1X)
                expect(result.shouldManuallyAdvance).toBe(true)
                expect(result.resolvedTimestamp).toBeCloseTo(currentTs + FPS_1X, 1)
                currentTs = result.resolvedTimestamp!
                frameState = result.newState
            }
        })
    })
})
