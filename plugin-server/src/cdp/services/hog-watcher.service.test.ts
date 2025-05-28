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
import { createExampleInvocation } from '../_tests/fixtures'
import { deleteKeysWithPrefix } from '../_tests/redis'
import { createInvocationResult } from '../utils/invocation-utils'

const mockNow: jest.Mock = require('../../../src/utils/now').now as any

const createResult = (options: {
    id: string
    duration?: number
    finished?: boolean
    error?: string
}): HogFunctionInvocationResult => {
    return createInvocationResult(
        {
            ...createExampleInvocation({ id: options.id }),
            id: 'invocation-id',
            teamId: 2,
            timings: [
                {
                    kind: 'hog',
                    duration_ms: options.duration ?? 0,
                },
            ],
        },
        {
            queue: 'hog',
        },
        {
            finished: options.finished ?? true,
            error: options.error,
            logs: [],
            metrics: [],
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
                    CDP_WATCHER_COST_TIMING_LOWER_MS: 100,
                    CDP_WATCHER_COST_TIMING_UPPER_MS: 100,
                    CDP_WATCHER_COST_TIMING: 1,
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

    const cases: [{ cost: number; state: number }, HogFunctionInvocationResult[]][] = [
        [{ cost: 0, state: 1 }, [createResult({ id: 'id1' })]],
        [
            { cost: 0, state: 1 },
            [createResult({ id: 'id1' }), createResult({ id: 'id1' }), createResult({ id: 'id1' })],
        ],
        [
            { cost: 0, state: 1 },
            [
                createResult({ id: 'id1', duration: 10 }),
                createResult({ id: 'id1', duration: 20 }),
                createResult({ id: 'id1', duration: 100 }),
            ],
        ],
        [
            { cost: 12, state: 1 },
            [
                createResult({ id: 'id1', duration: 1000 }),
                createResult({ id: 'id1', duration: 1000 }),
                createResult({ id: 'id1', duration: 1000 }),
            ],
        ],
        [{ cost: 20, state: 1 }, [createResult({ id: 'id1', duration: 5000 })]],
        [{ cost: 40, state: 1 }, [createResult({ id: 'id1', duration: 10000 })]],
        [
            { cost: 141, state: 1 },
            [
                createResult({ id: 'id1', duration: 5000 }),
                createResult({ id: 'id1', duration: 10000 }),
                createResult({ id: 'id1', duration: 20000 }),
            ],
        ],

        [{ cost: 100, state: 1 }, [createResult({ id: 'id1', error: 'errored!' })]],
    ]

    it.each(cases)('should update tokens based on results %s %s', async (expectedScore, results) => {
        await watcher.observeResults(results)
        const result = await watcher.getState('id1')

        expect(hub.CDP_WATCHER_BUCKET_SIZE - result.tokens).toEqual(expectedScore.cost)
        expect(result.state).toEqual(expectedScore.state)
    })

    it('should calculate costs per individual timing not based on total duration', async () => {
        // Create a result with multiple timings that would have different costs
        // if calculated individually vs. summed together
        const result = createResult({ id: 'id1', finished: true }) as HogFunctionInvocationResult

        // Replace the default timing with multiple timings
        result.invocation.timings = [
            { kind: 'hog', duration_ms: 100 }, // Below threshold, should have minimal cost
            { kind: 'hog', duration_ms: 100 }, // Below threshold, should have minimal cost
            { kind: 'hog', duration_ms: 100 }, // Below threshold, should have minimal cost
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
        let lotsOfResults = Array(10000).fill(createResult({ id: 'id1', error: 'error!' }))

        await watcher.observeResults(lotsOfResults)

        expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                {
                  "rating": -0.0001,
                  "state": 3,
                  "tokens": -1,
                }
            `)

        lotsOfResults = Array(10000).fill(createResult({ id: 'id2' }))

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
            createResult({ id: 'id1', duration: 10000 }),
            createResult({ id: 'id1', duration: 10000 }),
            createResult({ id: 'id1', duration: 10000 }),
        ])

        expect((await watcher.getState('id1')).tokens).toMatchInlineSnapshot(`9880`)
        advanceTime(1000)
        expect((await watcher.getState('id1')).tokens).toMatchInlineSnapshot(`9890`)
        advanceTime(10000)
        expect((await watcher.getState('id1')).tokens).toMatchInlineSnapshot(`9990`)
    })

    it('should remain disabled for period', async () => {
        const badResults = Array(100).fill(createResult({ id: 'id1', error: 'error!' }))

        await watcher.observeResults(badResults)

        expect(mockCeleryApplyAsync).toHaveBeenCalledTimes(1)
        expect(mockCeleryApplyAsync).toHaveBeenCalledWith(CELERY_TASK_ID, ['id1', HogWatcherState.disabledForPeriod])

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
                await watcher.observeResults([createResult({ id: 'id1', error: 'error!' })])
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

            await watcher.observeResults([createResult({ id: 'id1', error: 'error!' })])
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
