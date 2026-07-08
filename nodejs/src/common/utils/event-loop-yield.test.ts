import { Counter, register } from 'prom-client'

import {
    configureEventLoopYield,
    getEventLoopYieldThresholdMs,
    yieldEach,
    yieldEventLoopIfNeeded,
} from './event-loop-yield'

function busyWaitMs(ms: number): void {
    const start = performance.now()
    while (performance.now() - start < ms) {
        // spin — the whole point is to block the event loop
    }
}

async function getYieldCount(caller: string, waited: 'true' | 'false'): Promise<number> {
    const metric = register.getSingleMetric('event_loop_yield_total') as Counter | undefined
    if (!metric) {
        return 0
    }
    const data = await metric.get()
    const sample = data.values.find((v) => v.labels.caller === caller && v.labels.waited === waited)
    return sample?.value ?? 0
}

describe('event-loop-yield', () => {
    let originalThreshold: number

    beforeEach(() => {
        jest.useRealTimers()
        originalThreshold = getEventLoopYieldThresholdMs()
    })

    afterEach(async () => {
        configureEventLoopYield(originalThreshold)
        // Drain the singleton state — any in-flight setTimeout(0) needs to fire
        // so the next test starts with a fresh state.
        await new Promise((resolve) => setTimeout(resolve, 0))
    })

    describe('configuration', () => {
        it('uses the configured default threshold', () => {
            configureEventLoopYield(123)
            expect(getEventLoopYieldThresholdMs()).toBe(123)
        })
    })

    describe('yieldEventLoopIfNeeded', () => {
        it('returns the wrapped function result', async () => {
            const result = await yieldEventLoopIfNeeded('test', () => 42)
            expect(result).toBe(42)
        })

        it('awaits an async wrapped function', async () => {
            const result = await yieldEventLoopIfNeeded('test', async () => {
                await new Promise((resolve) => setTimeout(resolve, 0))
                return 'ok'
            })
            expect(result).toBe('ok')
        })

        it('still yields if the wrapped function throws', async () => {
            configureEventLoopYield(20)
            // Prime accumulated state so the next call's after-yield trips the threshold.
            await yieldEventLoopIfNeeded('test', () => busyWaitMs(40))
            const before = await getYieldCount('test', 'true')
            await expect(
                yieldEventLoopIfNeeded('test', () => {
                    busyWaitMs(40)
                    throw new Error('boom')
                })
            ).rejects.toThrow('boom')
            const after = await getYieldCount('test', 'true')
            // The wrapper should have yielded at least once even though fn threw.
            expect(after).toBeGreaterThan(before)
        })

        it('does not actually yield when accumulated work is below the threshold', async () => {
            configureEventLoopYield(10_000)
            const before = await getYieldCount('test', 'true')
            await yieldEventLoopIfNeeded('test', () => busyWaitMs(20))
            const after = await getYieldCount('test', 'true')
            expect(after - before).toBe(0)
        })

        it('actually yields when accumulated work crosses the threshold', async () => {
            configureEventLoopYield(20)
            const before = await getYieldCount('test', 'true')
            await yieldEventLoopIfNeeded('test', () => busyWaitMs(40))
            const after = await getYieldCount('test', 'true')
            // Either the before- or after-yield should have crossed the threshold.
            expect(after - before).toBeGreaterThan(0)
        })

        it('does not block the loop across many CPU-bound calls', async () => {
            configureEventLoopYield(20)

            let longestDelay = 0
            let lastTick = performance.now()
            const interval = setInterval(() => {
                const now = performance.now()
                longestDelay = Math.max(longestDelay, now - lastTick)
                lastTick = now
            }, 0)

            try {
                const blockMs = 30
                for (let i = 0; i < 10; i++) {
                    await yieldEventLoopIfNeeded('test', () => busyWaitMs(blockMs))
                }
                // 10 * 30 = 300ms total blocking. With yielding, longestDelay
                // should be close to one block + scheduling jitter. (If yielding
                // were broken, this would be ~300ms.)
                expect(longestDelay).toBeLessThan(blockMs * 4)
            } finally {
                clearInterval(interval)
            }
        })
    })

    describe('parallel callers', () => {
        it('keeps a setInterval making progress while two parallel workers are busy', async () => {
            // Two parallel producers in tight async loops. Without yielding, the
            // setInterval observer would be starved for the full duration.
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
                        await yieldEventLoopIfNeeded(id, () => busyWaitMs(blockMs))
                    }
                }
                await Promise.all([worker('worker-a'), worker('worker-b')])
            } finally {
                clearInterval(interval)
            }

            expect(longestDelay).toBeLessThan(totalBlockingWork / 2)
            // We should have observed at least one interval tick fire while the
            // workers were busy (otherwise we don't know yielding actually happened).
            expect(intervalTickCount).toBeGreaterThan(1)
        })

        it('serialized callers via promise chain keep the loop unblocked', async () => {
            // To prove the helper actually protects the loop end-to-end (matching
            // hog-exec.test.ts's longestDelay bound), callers must be serialized
            // so the setTimeout(0) macrotask can fire between them.
            const blockMs = 100
            const numberOfCallers = 10
            configureEventLoopYield(blockMs)

            let longestDelay = 0
            let lastTick = performance.now()
            const interval = setInterval(() => {
                const now = performance.now()
                longestDelay = Math.max(longestDelay, now - lastTick)
                lastTick = now
            }, 0)

            try {
                let chain: Promise<void> = Promise.resolve()
                for (let i = 0; i < numberOfCallers; i++) {
                    chain = chain.then(() => yieldEventLoopIfNeeded(`caller-${i}`, () => busyWaitMs(blockMs)))
                }
                await chain
                await new Promise((resolve) => setTimeout(resolve, 1))
                // With serialization, the setTimeout fires between each block,
                // so longestDelay should be ~ one block + scheduling jitter.
                expect(longestDelay).toBeLessThan(blockMs * 2.5)
            } finally {
                clearInterval(interval)
            }
        })

        it('does not unconditionally yield — fast callers below the threshold do not yield', async () => {
            // A caller that does no sync work should not yield (most of the
            // time). Even when sharing state with a slow caller that does yield,
            // fast callers should mostly count as "not waited".
            configureEventLoopYield(20)

            const slowCaller = async (): Promise<void> => {
                for (let i = 0; i < 3; i++) {
                    await yieldEventLoopIfNeeded('slow', () => busyWaitMs(40))
                }
            }
            const fastCaller = async (): Promise<void> => {
                for (let i = 0; i < 6; i++) {
                    await yieldEventLoopIfNeeded('fast', () => {})
                }
            }

            const beforeSlowWaited = await getYieldCount('slow', 'true')
            const beforeFastNot = await getYieldCount('fast', 'false')
            await Promise.all([slowCaller(), fastCaller()])
            const afterSlowWaited = await getYieldCount('slow', 'true')
            const afterFastNot = await getYieldCount('fast', 'false')

            // At least one slow call must have yielded.
            expect(afterSlowWaited - beforeSlowWaited).toBeGreaterThan(0)
            // At least one fast call must NOT have yielded.
            expect(afterFastNot - beforeFastNot).toBeGreaterThan(0)
        })
    })

    describe('yieldEach', () => {
        it('calls fn for every item in order with the right index', async () => {
            const items = ['a', 'b', 'c', 'd']
            const seen: Array<[string, number]> = []
            await yieldEach('test', items, (item, i) => {
                seen.push([item, i])
            })
            expect(seen).toEqual([
                ['a', 0],
                ['b', 1],
                ['c', 2],
                ['d', 3],
            ])
        })

        it('awaits async fn before moving on', async () => {
            const order: string[] = []
            await yieldEach('test', [1, 2, 3], async (item) => {
                order.push(`start-${item}`)
                await new Promise((resolve) => setTimeout(resolve, 0))
                order.push(`end-${item}`)
            })
            expect(order).toEqual(['start-1', 'end-1', 'start-2', 'end-2', 'start-3', 'end-3'])
        })

        it('actually yields the event loop during a CPU-bound batch', async () => {
            // Without yielding, longestDelay would equal the full batch wall time.
            configureEventLoopYield(20)

            let longestDelay = 0
            let lastTick = performance.now()
            const interval = setInterval(() => {
                const now = performance.now()
                longestDelay = Math.max(longestDelay, now - lastTick)
                lastTick = now
            }, 0)

            try {
                const blockMs = 30
                const items = Array.from({ length: 10 }, (_, i) => i)
                await yieldEach('test', items, () => busyWaitMs(blockMs))

                // 10 * 30 = 300ms total blocking. With yielding, longestDelay
                // should be close to one block + a little jitter. (If yielding
                // were broken, this would be ~300ms.)
                expect(longestDelay).toBeLessThan(blockMs * 4)
            } finally {
                clearInterval(interval)
            }
        })

        it('works on ArrayLike values, not just real arrays', async () => {
            const arrayLike: ArrayLike<string> = { 0: 'x', 1: 'y', 2: 'z', length: 3 }
            const seen: string[] = []
            await yieldEach('test', arrayLike, (item) => {
                seen.push(item)
            })
            expect(seen).toEqual(['x', 'y', 'z'])
        })

        it('handles empty arrays gracefully', async () => {
            const seen: string[] = []
            await yieldEach('test', [], (item) => {
                seen.push(item as string)
            })
            expect(seen).toEqual([])
        })
    })
})
