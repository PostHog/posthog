jest.mock('../../../src/utils/now', () => {
    return {
        now: jest.fn(() => Date.now()),
    }
})
import { CdpRedis, createCdpRedisPool } from '../../../src/cdp/redis'
import {
    BASE_REDIS_KEY,
    CELERY_TASK_ID,
    HogWatcherService,
    HogWatcherState,
} from '../../../src/cdp/services/hog-watcher.service'
import { HogFunctionInvocationResult } from '../../../src/cdp/types'
import { Hub } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { delay } from '../../../src/utils/utils'
import { createInvocation } from '../_tests/fixtures'
import { deleteKeysWithPrefix } from '../_tests/redis'

const mockNow: jest.Mock = require('../../../src/utils/now').now as any

const createHogResult = (options: {
    id: string
    duration?: number
    finished?: boolean
    error?: string
}): HogFunctionInvocationResult => {
    return {
        invocation: {
            ...createInvocation({ id: options.id }),
            id: 'invocation-id',
            teamId: 2,
            timings: [
                {
                    kind: 'hog',
                    duration_ms: options.duration ?? 0,
                },
            ],
        },
        finished: options.finished ?? true,
        error: options.error,
        logs: [],
    }
}

const createAsyncResult = (options: {
    id: string
    duration?: number
    finished?: boolean
    error?: string
}): HogFunctionInvocationResult => {
    return {
        invocation: {
            ...createInvocation({ id: options.id }),
            id: 'invocation-id',
            teamId: 2,
            timings: [
                {
                    kind: 'async_function',
                    duration_ms: options.duration ?? 0,
                },
            ],
        },
        finished: options.finished ?? true,
        error: options.error,
        logs: [],
    }
}

describe('HogWatcher', () => {
    describe('integration', () => {
        let now: number
        let hub: Hub
        let watcher: HogWatcherService
        let mockCeleryApplyAsync: jest.Mock
        let redis: CdpRedis

        beforeEach(async () => {
            hub = await createHub()
            hub.celery.applyAsync = mockCeleryApplyAsync = jest.fn()

            now = 1720000000000
            mockNow.mockReturnValue(now)

            redis = createCdpRedisPool(hub)
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)

            watcher = new HogWatcherService(hub, redis)
        })

        // Helper function to calculate cost based on duration and type
        const calculateCost = (durationMs: number, kind: 'hog' | 'async_function'): number => {
            if (kind === 'hog') {
                const lowerBound = hub.CDP_WATCHER_HOG_COST_TIMING_LOWER_MS
                const upperBound = hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS
                const costTiming = hub.CDP_WATCHER_HOG_COST_TIMING
                const ratio = Math.max(0, durationMs - lowerBound) / (upperBound - lowerBound)
                return Math.round(costTiming * ratio)
            } else {
                const lowerBound = hub.CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS
                const upperBound = hub.CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS
                const costTiming = hub.CDP_WATCHER_ASYNC_COST_TIMING
                const ratio = Math.max(0, durationMs - lowerBound) / (upperBound - lowerBound)
                return Math.round(costTiming * ratio)
            }
        }

        const advanceTime = (ms: number) => {
            now += ms
            mockNow.mockReturnValue(now)
        }

        const reallyAdvanceTime = async (ms: number) => {
            advanceTime(ms)
            await delay(ms)
        }

        afterEach(async () => {
            jest.useRealTimers()
            await closeHub(hub)
            jest.clearAllMocks()
        })

        it('should retrieve empty state', async () => {
            const res = await watcher.getStates(['id1', 'id2'])
            expect(res).toMatchInlineSnapshot(`
                {
                  "id1": {
                    "rating": 1,
                    "state": 1,
                    "tokens": 10000,
                  },
                  "id2": {
                    "rating": 1,
                    "state": 1,
                    "tokens": 10000,
                  },
                }
            `)
        })

        const cases: [{ cost: number; state: number }, HogFunctionInvocationResult[]][] = [
            [{ cost: 0, state: 1 }, [createAsyncResult({ id: 'id1' })]],
            [
                { cost: 0, state: 1 },
                [createAsyncResult({ id: 'id1' }), createAsyncResult({ id: 'id1' }), createAsyncResult({ id: 'id1' })],
            ],
            [
                { cost: 0, state: 1 },
                [
                    createAsyncResult({ id: 'id1', duration: 10 }),
                    createAsyncResult({ id: 'id1', duration: 20 }),
                    createAsyncResult({ id: 'id1', duration: 100 }),
                ],
            ],
            [
                { cost: 12, state: 1 },
                [
                    createAsyncResult({ id: 'id1', duration: 1000 }),
                    createAsyncResult({ id: 'id1', duration: 1000 }),
                    createAsyncResult({ id: 'id1', duration: 1000 }),
                ],
            ],
            [{ cost: 20, state: 1 }, [createAsyncResult({ id: 'id1', duration: 5000 })]],
            [{ cost: 40, state: 1 }, [createAsyncResult({ id: 'id1', duration: 10000 })]],
            [
                { cost: 141, state: 1 },
                [
                    createAsyncResult({ id: 'id1', duration: 5000 }),
                    createAsyncResult({ id: 'id1', duration: 10000 }),
                    createAsyncResult({ id: 'id1', duration: 20000 }),
                ],
            ],

            [{ cost: 100, state: 1 }, [createAsyncResult({ id: 'id1', error: 'errored!' })]],
        ]

        it.each(cases)('should update tokens based on results %s %s', async (expectedScore, results) => {
            await watcher.observeResults(results)
            const result = await watcher.getState('id1')

            expect(hub.CDP_WATCHER_BUCKET_SIZE - result.tokens).toEqual(expectedScore.cost)
            expect(result.state).toEqual(expectedScore.state)
        })

        it('should max out scores', async () => {
            let lotsOfResults = Array(10000).fill(createAsyncResult({ id: 'id1', error: 'error!' }))

            await watcher.observeResults(lotsOfResults)

            expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                {
                  "rating": -0.0001,
                  "state": 3,
                  "tokens": -1,
                }
            `)

            lotsOfResults = Array(10000).fill(createAsyncResult({ id: 'id2' }))

            await watcher.observeResults(lotsOfResults)

            expect(await watcher.getState('id2')).toMatchInlineSnapshot(`
                {
                  "rating": 1,
                  "state": 1,
                  "tokens": 10000,
                }
            `)
        })

        it('should refill over time', async () => {
            hub.CDP_WATCHER_REFILL_RATE = 10
            await watcher.observeResults([
                createAsyncResult({ id: 'id1', duration: 10000 }),
                createAsyncResult({ id: 'id1', duration: 10000 }),
                createAsyncResult({ id: 'id1', duration: 10000 }),
            ])

            expect((await watcher.getState('id1')).tokens).toMatchInlineSnapshot(`9880`)
            advanceTime(1000)
            expect((await watcher.getState('id1')).tokens).toMatchInlineSnapshot(`9890`)
            advanceTime(10000)
            expect((await watcher.getState('id1')).tokens).toMatchInlineSnapshot(`9990`)
        })

        describe('function type cost differences', () => {
            it('should apply higher cost to hog functions than async for same duration', async () => {
                // Same duration (300ms) but different function types
                const executionDuration = 300
                await watcher.observeResults([createHogResult({ id: 'hog1', duration: executionDuration })])
                await watcher.observeResults([createAsyncResult({ id: 'async1', duration: executionDuration })])

                const hogState = await watcher.getState('hog1')
                const asyncState = await watcher.getState('async1')

                // Calculate expected costs using the helper
                const hogCost = calculateCost(executionDuration, 'hog')
                const asyncCost = calculateCost(executionDuration, 'async_function')

                expect(10000 - hogState.tokens).toBe(hogCost)
                expect(10000 - asyncState.tokens).toBe(asyncCost)
                expect(10000 - hogState.tokens).toBeGreaterThan(10000 - asyncState.tokens)
            })

            it('should not apply any cost below lower bounds', async () => {
                // Both functions below their respective lower bounds
                await watcher.observeResults([createHogResult({ id: 'hog_min', duration: 25 })])
                await watcher.observeResults([createAsyncResult({ id: 'async_min', duration: 100 })])

                const hogState = await watcher.getState('hog_min')
                const asyncState = await watcher.getState('async_min')

                // Both should have no cost
                expect(10000 - hogState.tokens).toBe(0)
                expect(10000 - asyncState.tokens).toBe(0)
            })

            it('should penalize hog functions that exceed threshold by small amounts', async () => {
                // Test near-threshold values for hog functions
                await watcher.observeResults([createHogResult({ id: 'hog_60', duration: 60 })])
                await watcher.observeResults([createHogResult({ id: 'hog_80', duration: 80 })])
                await watcher.observeResults([createHogResult({ id: 'hog_100', duration: 100 })])

                // There should be a progressive, noticeable penalty even for small overages
                const tokens60 = (await watcher.getState('hog_60')).tokens
                const tokens80 = (await watcher.getState('hog_80')).tokens
                const tokens100 = (await watcher.getState('hog_100')).tokens

                // Ensure progressive penalties
                expect(10000 - tokens60).toBeGreaterThan(0) // Just over threshold should have some penalty
                expect(10000 - tokens80).toBeGreaterThan(10000 - tokens60) // Higher duration = higher penalty
                expect(10000 - tokens100).toBeGreaterThan(10000 - tokens80) // Even higher penalty
            })

            it('should calculate costs for multiple entries of the same type', async () => {
                // Create a result with multiple hog timing entries
                const result: HogFunctionInvocationResult = {
                    invocation: {
                        ...createInvocation({ id: 'multi_hog' }),
                        id: 'invocation-id',
                        teamId: 2,
                        timings: [
                            { kind: 'hog', duration_ms: 40 }, // Below threshold
                            { kind: 'hog', duration_ms: 80 }, // Above threshold
                            { kind: 'hog', duration_ms: 150 }, // Well above threshold
                        ],
                    },
                    finished: true,
                    logs: [],
                }

                await watcher.observeResults([result])
                const multiHogState = await watcher.getState('multi_hog')

                // Calculate expected costs using the helper
                const cost1 = calculateCost(40, 'hog')
                const cost2 = calculateCost(80, 'hog')
                const cost3 = calculateCost(150, 'hog')

                const expectedTotalCost = cost1 + cost2 + cost3

                // Total cost should be sum of individual timing costs
                expect(10000 - multiHogState.tokens).toBe(expectedTotalCost)
            })

            it('should handle complex mixed function scenarios correctly', async () => {
                // Create an invocation with multiple timing entries of both types
                const complexResult: HogFunctionInvocationResult = {
                    invocation: {
                        ...createInvocation({ id: 'complex_mixed' }),
                        id: 'invocation-id',
                        teamId: 2,
                        timings: [
                            { kind: 'hog', duration_ms: 50 }, // Just below hog threshold
                            { kind: 'async_function', duration_ms: 120 }, // Just above async threshold
                            { kind: 'hog', duration_ms: 90 }, // Above hog threshold
                            { kind: 'async_function', duration_ms: 800 }, // Higher async cost
                            { kind: 'hog', duration_ms: 200 }, // Higher hog cost
                        ],
                    },
                    finished: true,
                    logs: [],
                }

                await watcher.observeResults([complexResult])
                const complexState = await watcher.getState('complex_mixed')

                // Calculate expected costs using the helper
                const hogCost1 = calculateCost(50, 'hog')
                const asyncCost1 = calculateCost(120, 'async_function')
                const hogCost2 = calculateCost(90, 'hog')
                const asyncCost2 = calculateCost(800, 'async_function')
                const hogCost3 = calculateCost(200, 'hog')

                const expectedTotalCost = hogCost1 + asyncCost1 + hogCost2 + asyncCost2 + hogCost3

                // Total cost should be sum of all individual timing costs
                expect(10000 - complexState.tokens).toBe(expectedTotalCost)
            })
        })

        it('should remain disabled for period', async () => {
            const badResults = Array(100).fill(createAsyncResult({ id: 'id1', error: 'error!' }))

            await watcher.observeResults(badResults)

            expect(mockCeleryApplyAsync).toHaveBeenCalledTimes(1)
            expect(mockCeleryApplyAsync).toHaveBeenCalledWith(CELERY_TASK_ID, [
                'id1',
                HogWatcherState.disabledForPeriod,
            ])

            expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                {
                  "rating": 0,
                  "state": 3,
                  "tokens": 0,
                }
            `)

            advanceTime(10000)

            // Should still be disabled even though tokens have been refilled
            expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                {
                  "rating": 0.01,
                  "state": 3,
                  "tokens": 100,
                }
            `)
        })

        describe('forceStateChange', () => {
            it('should force healthy', async () => {
                await watcher.forceStateChange('id1', HogWatcherState.healthy)
                expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                    {
                      "rating": 1,
                      "state": 1,
                      "tokens": 10000,
                    }
                `)
                expect(mockCeleryApplyAsync).toHaveBeenCalledWith(CELERY_TASK_ID, ['id1', HogWatcherState.healthy])
            })
            it('should force degraded', async () => {
                await watcher.forceStateChange('id1', HogWatcherState.degraded)
                expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                    {
                      "rating": 0.8,
                      "state": 1,
                      "tokens": 8000,
                    }
                `)
                expect(mockCeleryApplyAsync).toHaveBeenCalledWith(CELERY_TASK_ID, ['id1', HogWatcherState.degraded])
            })
            it('should force disabledForPeriod', async () => {
                await watcher.forceStateChange('id1', HogWatcherState.disabledForPeriod)
                expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                    {
                      "rating": 0,
                      "state": 3,
                      "tokens": 0,
                    }
                `)
                expect(mockCeleryApplyAsync).toHaveBeenCalledWith(CELERY_TASK_ID, [
                    'id1',
                    HogWatcherState.disabledForPeriod,
                ])
            })
            it('should force disabledIndefinitely', async () => {
                await watcher.forceStateChange('id1', HogWatcherState.disabledIndefinitely)
                expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                    {
                      "rating": 0,
                      "state": 4,
                      "tokens": 0,
                    }
                `)
                expect(mockCeleryApplyAsync).toHaveBeenCalledWith(CELERY_TASK_ID, [
                    'id1',
                    HogWatcherState.disabledIndefinitely,
                ])
            })
        })

        describe('disable logic', () => {
            jest.retryTimes(3) // Timings are flakey and hard to test but we don't need it to be perfect
            beforeEach(() => {
                hub.CDP_WATCHER_BUCKET_SIZE = 100
                hub.CDP_WATCHER_DISABLED_TEMPORARY_TTL = 1 // Shorter ttl to help with testing
                hub.CDP_WATCHER_DISABLED_TEMPORARY_MAX_COUNT = 3
            })

            it('count the number of times it has been disabled', async () => {
                // Trigger the temporary disabled state 3 times
                for (let i = 0; i < 2; i++) {
                    await watcher.observeResults([createAsyncResult({ id: 'id1', error: 'error!' })])
                    expect((await watcher.getState('id1')).state).toEqual(HogWatcherState.disabledForPeriod)
                    await reallyAdvanceTime(1000)
                    expect((await watcher.getState('id1')).state).toEqual(HogWatcherState.degraded)
                }

                expect(mockCeleryApplyAsync).toHaveBeenCalledTimes(2)
                expect(mockCeleryApplyAsync.mock.calls[0]).toEqual([
                    CELERY_TASK_ID,
                    ['id1', HogWatcherState.disabledForPeriod],
                ])
                expect(mockCeleryApplyAsync.mock.calls[1]).toEqual([
                    CELERY_TASK_ID,
                    ['id1', HogWatcherState.disabledForPeriod],
                ])

                await watcher.observeResults([createAsyncResult({ id: 'id1', error: 'error!' })])
                expect((await watcher.getState('id1')).state).toEqual(HogWatcherState.disabledIndefinitely)
                await reallyAdvanceTime(1000)
                expect((await watcher.getState('id1')).state).toEqual(HogWatcherState.disabledIndefinitely)

                expect(mockCeleryApplyAsync).toHaveBeenCalledTimes(3)
                expect(mockCeleryApplyAsync.mock.calls[2]).toEqual([
                    CELERY_TASK_ID,
                    ['id1', HogWatcherState.disabledIndefinitely],
                ])
            })
        })
    })
})
