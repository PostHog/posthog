import { configureEventLoopYield, getEventLoopYieldThresholdMs, yieldEventLoopIfNeeded } from './event-loop-yield'

function busyWaitMs(ms: number): void {
    const start = performance.now()
    while (performance.now() - start < ms) {
        // spin — the whole point is to block the event loop
    }
}

describe('event-loop-yield', () => {
    let originalThreshold: number

    beforeEach(() => {
        jest.useRealTimers()
        originalThreshold = getEventLoopYieldThresholdMs()
    })

    afterEach(async () => {
        configureEventLoopYield(originalThreshold)
        // Drain the singleton state — any in-flight setTimeout(0) needs to fire so
        // the next test starts with a fresh state.
        await new Promise((resolve) => setTimeout(resolve, 0))
    })

    describe('configuration', () => {
        it('uses the configured default threshold', () => {
            configureEventLoopYield(123)
            expect(getEventLoopYieldThresholdMs()).toBe(123)
        })
    })

    describe('single caller', () => {
        it('returns false when nothing has accumulated yet', async () => {
            configureEventLoopYield(100)
            const result = await yieldEventLoopIfNeeded('test')
            expect(result).toBe(false)
        })

        it('returns true once accumulated sync work crosses the threshold', async () => {
            configureEventLoopYield(20)
            await yieldEventLoopIfNeeded('test') // primes the shared state
            busyWaitMs(40)
            const result = await yieldEventLoopIfNeeded('test')
            expect(result).toBe(true)
        })

        it('honors a per-call thresholdMs override below the default', async () => {
            configureEventLoopYield(10_000)
            await yieldEventLoopIfNeeded('test')
            busyWaitMs(40)
            const result = await yieldEventLoopIfNeeded('test', { thresholdMs: 20 })
            expect(result).toBe(true)
        })

        it('honors a per-call thresholdMs override above the default', async () => {
            configureEventLoopYield(5)
            await yieldEventLoopIfNeeded('test')
            busyWaitMs(20)
            const result = await yieldEventLoopIfNeeded('test', { thresholdMs: 10_000 })
            expect(result).toBe(false)
        })

        it('resets accumulated time after a yield so the next call starts fresh', async () => {
            configureEventLoopYield(20)
            await yieldEventLoopIfNeeded('test')
            busyWaitMs(40)
            const yielded = await yieldEventLoopIfNeeded('test')
            expect(yielded).toBe(true)
            // Right after yielding, a fresh call should be under the threshold again.
            const next = await yieldEventLoopIfNeeded('test')
            expect(next).toBe(false)
        })
    })

    describe('parallel callers', () => {
        it('shares accumulated time across callers', async () => {
            configureEventLoopYield(20)
            // Two callers prime the shared state at roughly the same moment.
            const [first, second] = await Promise.all([
                yieldEventLoopIfNeeded('caller-a'),
                yieldEventLoopIfNeeded('caller-b'),
            ])
            // Both saw essentially zero blocked time, both return false.
            expect([first, second]).toEqual([false, false])

            // Block past the threshold synchronously — neither caller has yielded yet.
            busyWaitMs(40)

            // Now both cross the threshold against the same shared state.
            const [third, fourth] = await Promise.all([
                yieldEventLoopIfNeeded('caller-a'),
                yieldEventLoopIfNeeded('caller-b'),
            ])
            expect([third, fourth]).toEqual([true, true])
        })

        it('resolves all queued waiters together when the macrotask fires', async () => {
            configureEventLoopYield(10)
            await yieldEventLoopIfNeeded('warmup')
            busyWaitMs(30)

            // Five parallel callers all cross the threshold against the same
            // state.promise. When setTimeout(0) fires, they should all resolve.
            const results = await Promise.all([
                yieldEventLoopIfNeeded('a'),
                yieldEventLoopIfNeeded('b'),
                yieldEventLoopIfNeeded('c'),
                yieldEventLoopIfNeeded('d'),
                yieldEventLoopIfNeeded('e'),
            ])
            expect(results).toEqual([true, true, true, true, true])
        })

        it('keeps a setInterval making progress while two parallel workers are busy', async () => {
            // Simulate two parallel producers doing batches of sync work in a tight
            // async loop, and make sure a setInterval observer keeps getting ticks
            // instead of being starved for the full duration of the work.
            configureEventLoopYield(30)

            const blockMs = 40
            const iterations = 5
            const workers = 2
            const totalBlockingWork = blockMs * iterations * workers // = 400ms

            let longestDelay = 0
            let intervalTickCount = 0
            let lastTick = performance.now()
            const interval = setInterval(() => {
                const now = performance.now()
                longestDelay = Math.max(longestDelay, now - lastTick)
                lastTick = now
                intervalTickCount += 1
            }, 0)

            try {
                const worker = async (id: string) => {
                    for (let i = 0; i < iterations; i++) {
                        busyWaitMs(blockMs)
                        await yieldEventLoopIfNeeded(id)
                    }
                }
                await Promise.all([worker('worker-a'), worker('worker-b')])
            } finally {
                clearInterval(interval)
            }

            // If yielding were broken, the interval would be starved for the
            // entire 400ms of blocking work. With yielding, longestDelay should
            // be bounded by a small multiple of (blockMs + threshold).
            expect(longestDelay).toBeLessThan(totalBlockingWork / 2)
            // And we should have actually observed multiple interval ticks
            // during the work (otherwise we don't really know yielding happened).
            expect(intervalTickCount).toBeGreaterThan(2)
        })

        it('does not unconditionally yield — fast callers below the threshold still return false', async () => {
            // A caller that does no sync work should normally return false. Even
            // when it shares state with a slow caller that does yield, fast
            // callers should at least sometimes get a false back (proving the
            // helper isn't degenerating into "always yield").
            configureEventLoopYield(20)

            const slowCaller = async (): Promise<boolean[]> => {
                const results: boolean[] = []
                for (let i = 0; i < 3; i++) {
                    busyWaitMs(40)
                    results.push(await yieldEventLoopIfNeeded('slow'))
                }
                return results
            }

            const fastCaller = async (): Promise<boolean[]> => {
                const results: boolean[] = []
                for (let i = 0; i < 6; i++) {
                    // No sync work — just keeps polling.
                    results.push(await yieldEventLoopIfNeeded('fast'))
                }
                return results
            }

            const [slow, fast] = await Promise.all([slowCaller(), fastCaller()])

            // Slow caller does 40ms sync blocks against a 20ms threshold, so at
            // least one of its calls must have yielded.
            expect(slow.some((r) => r)).toBe(true)
            // Fast caller does no sync work — at least one call must have
            // returned false.
            expect(fast.some((r) => r === false)).toBe(true)
        })
    })
})
