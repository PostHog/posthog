import { FrameState, initialFrameState, resolveFrameTimestamp, STUCK_FRAME_THRESHOLD } from './resolve-frame-timestamp'

const FPS_1X = 1 * (1000 / 60) // ~16.67ms
const THRESHOLD = STUCK_FRAME_THRESHOLD

function state(stuckFrames: number, lastAnimTimestamp: number | undefined): FrameState {
    return { stuckFrames, lastAnimTimestamp }
}

describe('resolveFrameTimestamp', () => {
    describe('core behavior', () => {
        it.each([
            {
                name: 'normal playback — new timestamp, not stuck',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(0, 900),
                expectedTs: 1000,
                expectedStuck: 0,
                expectedAdvance: false,
            },
            {
                name: 'window segment — same timestamp, first repeat (not stuck yet)',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(0, 1000),
                expectedTs: 1000,
                expectedStuck: 1,
                expectedAdvance: false,
            },
            {
                name: 'window segment — same timestamp, just under threshold',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(THRESHOLD - 2, 1000),
                expectedTs: 1000,
                expectedStuck: THRESHOLD - 1,
                expectedAdvance: false,
            },
            {
                name: 'window segment — same timestamp, hits threshold (manually advances)',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(THRESHOLD - 1, 1000),
                expectedTs: 500 + FPS_1X,
                expectedStuck: THRESHOLD,
                expectedAdvance: true,
            },
            {
                name: 'window segment — same timestamp, above threshold (stays stuck)',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(THRESHOLD, 1000),
                expectedTs: 500 + FPS_1X,
                expectedStuck: THRESHOLD + 1,
                expectedAdvance: true,
            },
            {
                name: 'window segment — new timestamp after nearly-stuck frames (resets counter)',
                rrwebTs: 1100,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(THRESHOLD - 1, 1000),
                expectedTs: 1100,
                expectedStuck: 0,
                expectedAdvance: false,
            },
            {
                name: 'gap segment — undefined timestamp (immediately advances)',
                rrwebTs: undefined,
                currentTs: 500,
                segmentKind: 'gap' as const,
                prev: state(0, undefined),
                expectedTs: 500 + FPS_1X,
                expectedStuck: 0,
                expectedAdvance: true,
            },
            {
                name: 'gap segment — undefined timestamp, no currentTimestamp (cannot advance)',
                rrwebTs: undefined,
                currentTs: undefined,
                segmentKind: 'gap' as const,
                prev: state(0, undefined),
                expectedTs: undefined,
                expectedStuck: 0,
                expectedAdvance: true,
            },
            {
                name: 'window segment — undefined timestamp (does not advance, bail out downstream)',
                rrwebTs: undefined,
                currentTs: 500,
                segmentKind: 'window' as const,
                prev: state(0, undefined),
                expectedTs: undefined,
                expectedStuck: 0,
                expectedAdvance: false,
            },
            {
                name: 'gap segment — defined timestamp, first repeat (rrweb is playing skip-inactivity)',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'gap' as const,
                prev: state(0, 1000),
                expectedTs: 1000,
                expectedStuck: 1,
                expectedAdvance: false,
            },
            {
                name: 'gap segment — defined timestamp, hits stuck threshold',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'gap' as const,
                prev: state(THRESHOLD - 1, 1000),
                expectedTs: 500 + FPS_1X,
                expectedStuck: THRESHOLD,
                expectedAdvance: true,
            },
            {
                name: 'buffer segment — stuck at threshold (advances, buffer check is downstream)',
                rrwebTs: 1000,
                currentTs: 500,
                segmentKind: 'buffer' as const,
                prev: state(THRESHOLD - 1, 1000),
                expectedTs: 500 + FPS_1X,
                expectedStuck: THRESHOLD,
                expectedAdvance: true,
            },
            {
                name: 'buffer segment — undefined timestamp (does not advance, not a gap)',
                rrwebTs: undefined,
                currentTs: 500,
                segmentKind: 'buffer' as const,
                prev: state(0, undefined),
                expectedTs: undefined,
                expectedStuck: 0,
                expectedAdvance: false,
            },
            {
                name: 'no segment — undefined timestamp (does not advance)',
                rrwebTs: undefined,
                currentTs: 500,
                segmentKind: undefined,
                prev: state(0, undefined),
                expectedTs: undefined,
                expectedStuck: 0,
                expectedAdvance: false,
            },
        ])('$name', ({ rrwebTs, currentTs, segmentKind, prev, expectedTs, expectedStuck, expectedAdvance }) => {
            const result = resolveFrameTimestamp(rrwebTs, currentTs, segmentKind, FPS_1X, prev)
            if (expectedTs === undefined) {
                expect(result.resolvedTimestamp).toBeUndefined()
            } else {
                expect(result.resolvedTimestamp).toBeCloseTo(expectedTs, 1)
            }
            expect(result.newState.stuckFrames).toBe(expectedStuck)
            expect(result.shouldManuallyAdvance).toBe(expectedAdvance)
        })
    })

    describe('edge cases', () => {
        it('speed affects advance rate — 2x speed advances by ~33.34ms', () => {
            const fps2x = 2 * (1000 / 60)
            const result = resolveFrameTimestamp(1000, 500, 'window', fps2x, state(THRESHOLD - 1, 1000))
            expect(result.resolvedTimestamp).toBeCloseTo(500 + fps2x, 1)
        })

        it('stuck counter tracks lastAnimTimestamp correctly through undefined', () => {
            // Frame 1: undefined (gap) — resets to 0
            const r1 = resolveFrameTimestamp(undefined, 100, 'gap', FPS_1X, state(3, 1000))
            expect(r1.newState.stuckFrames).toBe(0)
            expect(r1.newState.lastAnimTimestamp).toBeUndefined()

            // Frame 2: defined again — resets to 0 (new timestamp vs undefined)
            const r2 = resolveFrameTimestamp(2000, 200, 'window', FPS_1X, r1.newState)
            expect(r2.newState.stuckFrames).toBe(0)
        })
    })

    describe('multi-frame sequences', () => {
        it('normal playback — increasing timestamps never trigger stuck', () => {
            let frameState = initialFrameState()
            for (let i = 0; i < 20; i++) {
                const result = resolveFrameTimestamp(1000 + i * 17, 1000 + i * 17, 'window', FPS_1X, frameState)
                expect(result.shouldManuallyAdvance).toBe(false)
                expect(result.newState.stuckFrames).toBe(0)
                frameState = result.newState
            }
        })

        it('temporary freeze then recovery — frames under threshold, then rrweb resumes', () => {
            let frameState = initialFrameState()
            const stuckTs = 5000

            // THRESHOLD - 1 frames at the same timestamp (under threshold)
            for (let i = 0; i < THRESHOLD - 1; i++) {
                const result = resolveFrameTimestamp(stuckTs, stuckTs, 'window', FPS_1X, frameState)
                expect(result.shouldManuallyAdvance).toBe(false)
                expect(result.resolvedTimestamp).toBe(stuckTs)
                frameState = result.newState
            }
            // first frame sets 0 (new ts), subsequent frames increment
            expect(frameState.stuckFrames).toBe(THRESHOLD - 2)

            // rrweb resumes with a new timestamp
            const recovery = resolveFrameTimestamp(5017, 5000, 'window', FPS_1X, frameState)
            expect(recovery.shouldManuallyAdvance).toBe(false)
            expect(recovery.resolvedTimestamp).toBe(5017)
            expect(recovery.newState.stuckFrames).toBe(0)
        })

        it('true stuck → manual advance chain', () => {
            let frameState = initialFrameState()
            const stuckTs = 5000
            let currentTs = stuckTs

            // THRESHOLD + 1 frames stuck at the same timestamp
            for (let i = 0; i < THRESHOLD + 1; i++) {
                const result = resolveFrameTimestamp(stuckTs, currentTs, 'window', FPS_1X, frameState)
                if (i < THRESHOLD) {
                    expect(result.shouldManuallyAdvance).toBe(false)
                    expect(result.resolvedTimestamp).toBe(stuckTs)
                } else {
                    // First frame past threshold: stuck! manually advance
                    expect(result.shouldManuallyAdvance).toBe(true)
                    expect(result.resolvedTimestamp).toBeCloseTo(currentTs + FPS_1X, 1)
                    currentTs = result.resolvedTimestamp!
                }
                frameState = result.newState
            }

            // Subsequent frames continue advancing (rrweb still stuck)
            for (let i = 0; i < 3; i++) {
                const result = resolveFrameTimestamp(stuckTs, currentTs, 'window', FPS_1X, frameState)
                expect(result.shouldManuallyAdvance).toBe(true)
                expect(result.resolvedTimestamp).toBeCloseTo(currentTs + FPS_1X, 1)
                currentTs = result.resolvedTimestamp!
                frameState = result.newState
            }
        })

        it('gap traversal — each frame advances by fps', () => {
            let frameState = initialFrameState()
            let currentTs = 10000

            for (let i = 0; i < 5; i++) {
                const result = resolveFrameTimestamp(undefined, currentTs, 'gap', FPS_1X, frameState)
                expect(result.shouldManuallyAdvance).toBe(true)
                expect(result.resolvedTimestamp).toBeCloseTo(currentTs + FPS_1X, 1)
                currentTs = result.resolvedTimestamp!
                frameState = result.newState
                // stuck counter stays at 0 because undefined !== undefined doesn't increment
                expect(frameState.stuckFrames).toBe(0)
            }
        })
    })
})
