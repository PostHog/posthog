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
import { Hub } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { delay } from '../../../src/utils/utils'
import { createExampleInvocation } from '../_tests/fixtures'
import { deleteKeysWithPrefix } from '../_tests/redis'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'

const mockNow: jest.Mock = require('../../../src/utils/now').now as any

const createResult = (options: {
    id: string
    duration?: number
    finished?: boolean
    error?: string
    kind?: 'hog' | 'async_function'
}): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> => {
    const invocation = createExampleInvocation({ id: options.id, team_id: 2 })
    invocation.state.timings = [
        {
            kind: options.kind ?? 'hog',
            duration_ms: options.duration ?? 0,
        },
    ]

    return createInvocationResult(
        invocation,
        {
            queue: options.kind === 'async_function' ? 'fetch' : 'hog',
        },
        {
            finished: options.finished ?? true,
            error: options.error,
        }
    )
}

describe('HogWatcher', () => {
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

    const advanceTime = (ms: number) => {
        now += ms
        mockNow.mockReturnValue(now)
    }

    const reallyAdvanceTime = async (ms: number) => {
        advanceTime(ms)
        await delay(ms)
    }

    // Helper function to calculate cost based on duration and type
    const calculateCost = (durationMs: number, kind: 'hog' | 'async_function'): number => {
        if (kind === 'hog') {
            const lowerBound = hub.CDP_WATCHER_HOG_COST_TIMING_LOWER_MS
            const upperBound = hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS
            const costTiming = hub.CDP_WATCHER_HOG_COST_TIMING
            const ratio = Math.max(durationMs - lowerBound, 0) / (upperBound - lowerBound)
            return Math.round(costTiming * ratio)
        } else {
            const asyncLowerBound = hub.CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS
            const asyncUpperBound = hub.CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS
            const asyncCostTiming = hub.CDP_WATCHER_ASYNC_COST_TIMING
            const asyncRatio = Math.max(durationMs - asyncLowerBound, 0) / (asyncUpperBound - asyncLowerBound)
            return Math.round(asyncCostTiming * asyncRatio)
        }
    }

    afterEach(async () => {
        jest.useRealTimers()
        await closeHub(hub)
        jest.clearAllMocks()
    })

    it('should validate the bounds configuration', () => {
        expect(() => {
            const _badWatcher = new HogWatcherService(
                {
                    ...hub,
                    CDP_WATCHER_HOG_COST_TIMING_LOWER_MS: 100,
                    CDP_WATCHER_HOG_COST_TIMING_UPPER_MS: 100,
                    CDP_WATCHER_HOG_COST_TIMING: 1,
                    CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS: 100,
                    CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS: 100,
                    CDP_WATCHER_ASYNC_COST_TIMING: 1,
                },
                redis
            )
        }).toThrow(
            'Lower bound for kind hog of 100ms must be lower than upper bound of 100ms. This is a configuration error.'
        )
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

    const cases: [
        { name: string; cost: number; state: number },
        CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>[]
    ][] = [
        [{ name: 'single default result', cost: 0, state: 1 }, [createResult({ id: 'id1' })]],
        [
            { name: 'three default results', cost: 0, state: 1 },
            [createResult({ id: 'id1' }), createResult({ id: 'id1' }), createResult({ id: 'id1' })],
        ],
        [
            { name: 'three small durations', cost: 0, state: 1 },
            [
                createResult({ id: 'id1', duration: 10 }),
                createResult({ id: 'id1', duration: 20 }),
                createResult({ id: 'id1', duration: 30 }),
            ],
        ],
        [
            { name: 'three 1000ms durations', cost: 12, state: 1 },
            [
                createResult({ id: 'id1', duration: 1000, kind: 'async_function' }),
                createResult({ id: 'id1', duration: 1000, kind: 'async_function' }),
                createResult({ id: 'id1', duration: 1000, kind: 'async_function' }),
            ],
        ],
        [
            { name: 'single 5000ms', cost: 20, state: 1 },
            [createResult({ id: 'id1', duration: 5000, kind: 'async_function' })],
        ],
        [
            { name: 'single 10000ms', cost: 40, state: 1 },
            [createResult({ id: 'id1', duration: 10000, kind: 'async_function' })],
        ],
        [
            { name: 'three large durations (should sum)', cost: 141, state: 1 },
            [
                createResult({ id: 'id1', duration: 5000, kind: 'async_function' }),
                createResult({ id: 'id1', duration: 10000, kind: 'async_function' }),
                createResult({ id: 'id1', duration: 20000, kind: 'async_function' }),
            ],
        ],
    ]

    it.each(cases)('%s', async (expectedScore, results) => {
        await watcher.observeResults(results)
        const result = await watcher.getState('id1')
        expect(hub.CDP_WATCHER_BUCKET_SIZE - result.tokens).toEqual(expectedScore.cost)
        expect(result.state).toEqual(expectedScore.state)
    })

    it('should calculate costs per individual timing not based on total duration', async () => {
        // Create a result with multiple timings that would have different costs
        // if calculated individually vs. summed together
        const result = createResult({
            id: 'id1',
            finished: true,
            kind: 'async_function',
        }) as CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>

        // Replace the default timing with multiple timings
        result.invocation.state.timings = [
            { kind: 'async_function', duration_ms: 90 }, // Below threshold, should have minimal cost
            { kind: 'async_function', duration_ms: 90 }, // Below threshold, should have minimal cost
            { kind: 'async_function', duration_ms: 90 }, // Below threshold, should have minimal cost
        ]

        // If using individual timings (correct): each timing has a small cost
        // If using total duration (incorrect): 300ms total would have a higher cost

        await watcher.observeResults([result])
        const state = await watcher.getState('id1')

        // Expected: each 100ms timing has minimal cost since it's below the lower threshold
        // This is checking that we're not summing them into a 300ms duration
        const expectedIndividualCost = 0 // Three 100ms timings each have minimal/zero cost
        const totalCost = hub.CDP_WATCHER_BUCKET_SIZE - state.tokens

        expect(totalCost).toEqual(expectedIndividualCost)
    })

    it('should max out scores', async () => {
        let lotsOfResults = Array(10000).fill(createResult({ id: 'id1', duration: 25000, kind: 'async_function' }))

        await watcher.observeResults(lotsOfResults)

        expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                {
                  "rating": -0.0001,
                  "state": 3,
                  "tokens": -1,
                }
            `)

        lotsOfResults = Array(10000).fill(createResult({ id: 'id2', kind: 'async_function' }))

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
            createResult({ id: 'id1', duration: 10000, kind: 'async_function' }),
            createResult({ id: 'id1', duration: 10000, kind: 'async_function' }),
            createResult({ id: 'id1', duration: 10000, kind: 'async_function' }),
        ])

        expect((await watcher.getState('id1')).tokens).toMatchInlineSnapshot(`9880`)
        advanceTime(1000)
        expect((await watcher.getState('id1')).tokens).toMatchInlineSnapshot(`9890`)
        advanceTime(10000)
        expect((await watcher.getState('id1')).tokens).toMatchInlineSnapshot(`9990`)
    })

    it('should remain disabled for period', async () => {
        const badResults = Array(100).fill(createResult({ id: 'id1', duration: 25000, kind: 'async_function' }))

        await watcher.observeResults(badResults)

        expect(mockCeleryApplyAsync).toHaveBeenCalledTimes(1)
        expect(mockCeleryApplyAsync).toHaveBeenCalledWith(CELERY_TASK_ID, ['id1', HogWatcherState.disabledForPeriod])

        expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                {
                  "rating": -0.0001,
                  "state": 3,
                  "tokens": -1,
                }
            `)

        advanceTime(10_000)

        // Should still be disabled even though tokens have been refilled
        expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                {
                  "rating": 0.0099,
                  "state": 3,
                  "tokens": 99,
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
                await watcher.observeResults([createResult({ id: 'id1', duration: 25000, kind: 'async_function' })])
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

            await watcher.observeResults([createResult({ id: 'id1', duration: 50000, kind: 'async_function' })])
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

    describe('function type cost differences', () => {
        it('should apply higher cost to hog functions than async for same duration', async () => {
            // Same duration (300ms) but different function types
            const executionDuration = 300
            await watcher.observeResults([createResult({ id: 'hog1', duration: executionDuration, kind: 'hog' })])
            await watcher.observeResults([
                createResult({ id: 'async1', duration: executionDuration, kind: 'async_function' }),
            ])

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
            await watcher.observeResults([createResult({ id: 'hog_min', duration: 25 })])
            await watcher.observeResults([createResult({ id: 'async_min', duration: 100, kind: 'async_function' })])

            const hogState = await watcher.getState('hog_min')
            const asyncState = await watcher.getState('async_min')

            // Both should have no cost
            expect(10000 - hogState.tokens).toBe(0)
            expect(10000 - asyncState.tokens).toBe(0)
        })

        it('should penalize hog functions that exceed threshold by small amounts', async () => {
            // Test near-threshold values for hog functions
            await watcher.observeResults([createResult({ id: 'hog_60', duration: 60 })])
            await watcher.observeResults([createResult({ id: 'hog_80', duration: 80 })])
            await watcher.observeResults([createResult({ id: 'hog_100', duration: 100 })])

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
            const result = createResult({ id: 'multi_hog', duration: 0, kind: 'hog' })
            result.invocation.state.timings = [
                { kind: 'hog', duration_ms: 40 },
                { kind: 'hog', duration_ms: 80 },
                { kind: 'hog', duration_ms: 150 },
            ]

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
            const baseResult = createResult({ id: 'complex_mixed', duration: 0, kind: 'hog' })
            // Overwrite timings with a mix of hog and async_function timings
            baseResult.invocation.state.timings = [
                { kind: 'hog', duration_ms: 50 },
                { kind: 'async_function', duration_ms: 120 },
                { kind: 'hog', duration_ms: 90 },
                { kind: 'async_function', duration_ms: 800 },
                { kind: 'hog', duration_ms: 200 },
            ]

            await watcher.observeResults([baseResult])
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
})
