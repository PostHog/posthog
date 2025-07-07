jest.mock('~/utils/posthog', () => {
    return {
        captureTeamEvent: jest.fn(),
    }
})

import { Hub, ProjectId, Team } from '../../../types'
import { closeHub, createHub } from '../../../utils/db/hub'
import { delay } from '../../../utils/utils'
import { createExampleInvocation } from '../../_tests/fixtures'
import { deleteKeysWithPrefix } from '../../_tests/redis'
import { CdpRedis, createCdpRedisPool } from '../../redis'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../../types'
import { createInvocationResult } from '../../utils/invocation-utils'
import { BASE_REDIS_KEY, CELERY_TASK_ID, HogWatcherService, HogWatcherState } from './hog-watcher.service'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')
const mockCaptureTeamEvent: jest.Mock = require('~/utils/posthog').captureTeamEvent as any

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
        {},
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
        const costsMapping = {
            hog: {
                lowerBound: hub.CDP_WATCHER_HOG_COST_TIMING_LOWER_MS,
                upperBound: hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
                cost: hub.CDP_WATCHER_HOG_COST_TIMING,
            },
            async_function: {
                lowerBound: hub.CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS,
                upperBound: hub.CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS,
                cost: hub.CDP_WATCHER_ASYNC_COST_TIMING,
            },
        }

        const costConfig = costsMapping[kind]
        const ratio = Math.max(durationMs - costConfig.lowerBound, 0) / (costConfig.upperBound - costConfig.lowerBound)
        return Math.round(costConfig.cost * ratio)
    }

    const observe = async (options: {
        id: string
        duration?: number
        kind?: 'hog' | 'async_function'
        count?: number
    }): Promise<void> => {
        await watcher.observeResults(Array(options.count ?? 1).fill(createResult(options as any)))
    }

    const tokensUsed = async (id: string): Promise<number> => {
        const { tokens } = await watcher.getState(id)
        return hub.CDP_WATCHER_BUCKET_SIZE - tokens
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
        [
            { name: 'should calculate cost and state for single default result', cost: 0, state: 1 },
            [createResult({ id: 'id1' })],
        ],
        [
            { name: 'should calculate cost and state for multiple default results', cost: 0, state: 1 },
            [createResult({ id: 'id1' }), createResult({ id: 'id1' }), createResult({ id: 'id1' })],
        ],
        [
            { name: 'should calculate cost and state for small durations', cost: 0, state: 1 },
            [
                createResult({ id: 'id1', duration: 10 }),
                createResult({ id: 'id1', duration: 20 }),
                createResult({ id: 'id1', duration: 30 }),
            ],
        ],
        [
            { name: 'should calculate cost and state for medium durations', cost: 12, state: 1 },
            [
                createResult({ id: 'id1', duration: 1000, kind: 'async_function' }),
                createResult({ id: 'id1', duration: 1000, kind: 'async_function' }),
                createResult({ id: 'id1', duration: 1000, kind: 'async_function' }),
            ],
        ],
        [
            { name: 'should calculate cost and state for single large duration', cost: 20, state: 1 },
            [createResult({ id: 'id1', duration: 5000, kind: 'async_function' })],
        ],
        [
            { name: 'should calculate cost and state for single very large duration', cost: 40, state: 1 },
            [createResult({ id: 'id1', duration: 10000, kind: 'async_function' })],
        ],
        [
            { name: 'should calculate cumulative cost and state for multiple large durations', cost: 141, state: 1 },
            [
                createResult({ id: 'id1', duration: 5000, kind: 'async_function' }),
                createResult({ id: 'id1', duration: 10000, kind: 'async_function' }),
                createResult({ id: 'id1', duration: 20000, kind: 'async_function' }),
            ],
        ],
    ]

    it.each(cases.map(([meta, results]) => [meta.name, meta, results]))('%s', async (name, expectedScore, results) => {
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
        beforeEach(() => {
            hub.teamManager.getTeam = jest.fn().mockResolvedValue({
                id: 2,
                project_id: 1 as ProjectId,
                uuid: 'test-uuid',
                organization_id: 'organization-id',
                name: 'testTeam',
                anonymize_ips: false,
                api_token: 'token',
                slack_incoming_webhook: '',
                session_recording_opt_in: false,
                ingested_event: true,
            } as Team)
        })

        const hogFunction = createResult({ id: 'id1' }).invocation.hogFunction
        it('should force healthy', async () => {
            await watcher.forceStateChange(hogFunction, HogWatcherState.healthy)
            expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                    {
                      "rating": 1,
                      "state": 1,
                      "tokens": 10000,
                    }
                `)
            expect(mockCeleryApplyAsync).toHaveBeenCalledWith(CELERY_TASK_ID, ['id1', HogWatcherState.healthy])
            expect(mockCaptureTeamEvent).toHaveBeenCalledWith(expect.any(Object), 'hog_function_state_change', {
                hog_function_id: hogFunction.id,
                hog_function_type: hogFunction.type,
                hog_function_name: hogFunction.name,
                hog_function_template_id: hogFunction.template_id,
                state: HogWatcherState[HogWatcherState.healthy],
            })
        })
        it('should force degraded', async () => {
            await watcher.forceStateChange(hogFunction, HogWatcherState.degraded)
            expect(await watcher.getState('id1')).toMatchInlineSnapshot(`
                    {
                      "rating": 0.8,
                      "state": 1,
                      "tokens": 8000,
                    }
                `)
            expect(mockCeleryApplyAsync).toHaveBeenCalledWith(CELERY_TASK_ID, ['id1', HogWatcherState.degraded])
            expect(mockCaptureTeamEvent).toHaveBeenCalledWith(expect.any(Object), 'hog_function_state_change', {
                hog_function_id: hogFunction.id,
                hog_function_type: hogFunction.type,
                hog_function_name: hogFunction.name,
                hog_function_template_id: hogFunction.template_id,
                state: HogWatcherState[HogWatcherState.degraded],
            })
        })
        it('should force disabledForPeriod', async () => {
            await watcher.forceStateChange(hogFunction, HogWatcherState.disabledForPeriod)
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
            expect(mockCaptureTeamEvent).toHaveBeenCalledWith(expect.any(Object), 'hog_function_state_change', {
                hog_function_id: hogFunction.id,
                hog_function_type: hogFunction.type,
                hog_function_name: hogFunction.name,
                hog_function_template_id: hogFunction.template_id,
                state: HogWatcherState[HogWatcherState.disabledForPeriod],
            })
        })
        it('should force disabledIndefinitely', async () => {
            await watcher.forceStateChange(hogFunction, HogWatcherState.disabledIndefinitely)
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
            expect(mockCaptureTeamEvent).toHaveBeenCalledWith(expect.any(Object), 'hog_function_state_change', {
                hog_function_id: hogFunction.id,
                hog_function_type: hogFunction.type,
                hog_function_name: hogFunction.name,
                hog_function_template_id: hogFunction.template_id,
                state: HogWatcherState[HogWatcherState.disabledIndefinitely],
            })
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
        const singleTimingCases: Array<[string, { id: string; duration: number; kind: 'hog' | 'async_function' }]> = [
            ['hog below threshold', { id: 'hog_min', duration: 25, kind: 'hog' }],
            ['async below threshold', { id: 'async_min', duration: 100, kind: 'async_function' }],
            ['hog 60 ms', { id: 'hog_60', duration: 60, kind: 'hog' }],
            ['hog 80 ms', { id: 'hog_80', duration: 80, kind: 'hog' }],
            ['hog 100 ms', { id: 'hog_100', duration: 100, kind: 'hog' }],
            ['hog 300 ms', { id: 'hog1', duration: 300, kind: 'hog' }],
            ['async 300 ms', { id: 'async1', duration: 300, kind: 'async_function' }],
        ]

        it.each(singleTimingCases)('applies correct cost – %s', async (_name, opts) => {
            await observe(opts)
            expect(await tokensUsed(opts.id)).toBe(calculateCost(opts.duration, opts.kind))
        })

        it('charges hog functions more than async functions for same duration', async () => {
            await observe({ id: 'hog_cmp', duration: 300, kind: 'hog' })
            await observe({ id: 'async_cmp', duration: 300, kind: 'async_function' })

            expect(await tokensUsed('hog_cmp')).toBeGreaterThan(await tokensUsed('async_cmp'))
        })

        type Timing = { kind: 'hog' | 'async_function'; duration_ms: number }
        const buildResultFromTimings = (
            id: string,
            timings: Timing[]
        ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> => {
            const result = createResult({ id, duration: 0, kind: timings[0].kind })
            result.invocation.state.timings = timings
            return result
        }

        const multiTimingCases: Array<[string, { id: string; timings: Timing[] }]> = [
            [
                'multiple hog timings',
                {
                    id: 'multi_hog',
                    timings: [
                        { kind: 'hog', duration_ms: 40 },
                        { kind: 'hog', duration_ms: 80 },
                        { kind: 'hog', duration_ms: 150 },
                    ],
                },
            ],
            [
                'complex hog/async mix',
                {
                    id: 'complex_mixed',
                    timings: [
                        { kind: 'hog', duration_ms: 50 },
                        { kind: 'async_function', duration_ms: 120 },
                        { kind: 'hog', duration_ms: 90 },
                        { kind: 'async_function', duration_ms: 800 },
                        { kind: 'hog', duration_ms: 200 },
                    ],
                },
            ],
        ]

        it.each(multiTimingCases)('applies correct cost – %s', async (_name, { id, timings }) => {
            await watcher.observeResults([buildResultFromTimings(id, timings)])

            const expectedTotalCost = timings.reduce((acc, t) => acc + calculateCost(t.duration_ms, t.kind), 0)

            expect(await tokensUsed(id)).toBe(expectedTotalCost)
        })
    })
})
