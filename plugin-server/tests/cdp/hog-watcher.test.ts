jest.mock('../../src/utils/now', () => {
    return {
        now: jest.fn(() => Date.now()),
    }
})

import {
    BASE_REDIS_KEY,
    calculateRating,
    deriveCurrentState,
    DISABLE_THRESHOLD,
    DISABLED_PERIOD,
    getAverageRating,
    HogWatcher,
    HogWatcherActiveObservations,
    HogWatcherObservationPeriod,
    HogWatcherState,
    HogWatcherStatePeriod,
    OBSERVATION_PERIOD,
    OVERFLOW_THRESHOLD,
    periodTimestamp,
} from '../../src/cdp/hog-watcher'
import { HogFunctionInvocationAsyncResponse, HogFunctionInvocationResult } from '../../src/cdp/types'
import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { delay } from '../../src/utils/utils'
import { deleteKeysWithPrefix } from '../helpers/redis'

const mockNow: jest.Mock = require('../../src/utils/now').now as any

const createResult = (id: string, finished = true, error?: string): HogFunctionInvocationResult => {
    return {
        hogFunctionId: id,
        finished,
        error,
    } as HogFunctionInvocationResult
}

const createAsyncResponse = (id: string, success = true): HogFunctionInvocationAsyncResponse => {
    return {
        hogFunctionId: id,
        error: success ? null : 'error',
    } as HogFunctionInvocationAsyncResponse
}

describe('HogWatcher', () => {
    describe('calculateRating', () => {
        // TODO: Change rating to account for numbers as well - low volume failures can still have a high rating as their impact is not so bad
        const cases: Array<[Partial<HogWatcherObservationPeriod>, number]> = [
            [{ successes: 9, failures: 1 }, 0.9],
            [{ successes: 1, failures: 1 }, 0.5],
            [{ successes: 0, failures: 1 }, 0],
            [{ successes: 1, failures: 0 }, 1],
            [{ asyncFunctionSuccesses: 9, asyncFunctionFailures: 1 }, 0.9],
            [{ asyncFunctionSuccesses: 1, asyncFunctionFailures: 1 }, 0.5],
            [{ asyncFunctionSuccesses: 0, asyncFunctionFailures: 1 }, 0],
            [{ asyncFunctionSuccesses: 1, asyncFunctionFailures: 0 }, 1],

            // Mixed results - currently whichever is worse is the rating
            [{ successes: 9, failures: 1, asyncFunctionSuccesses: 1, asyncFunctionFailures: 1 }, 0.5],
            [{ successes: 1, failures: 1, asyncFunctionSuccesses: 9, asyncFunctionFailures: 1 }, 0.5],
            [{ successes: 1, failures: 1, asyncFunctionSuccesses: 1, asyncFunctionFailures: 1 }, 0.5],
            [{ successes: 0, failures: 0, asyncFunctionSuccesses: 9, asyncFunctionFailures: 1 }, 0.9],
        ]

        it.each(cases)('should calculate the rating %s of %s', (vals, rating) => {
            const observation: HogWatcherObservationPeriod = {
                timestamp: Date.now(),
                successes: 0,
                failures: 0,
                asyncFunctionFailures: 0,
                asyncFunctionSuccesses: 0,
                ...vals,
            }
            expect(calculateRating(observation)).toBe(rating)
        })
    })

    describe('HogWatcherActiveObservations', () => {
        let observer: HogWatcherActiveObservations

        beforeEach(() => {
            observer = new HogWatcherActiveObservations()
            jest.useFakeTimers()
            jest.setSystemTime(1719229670000)
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('should update the observation', () => {
            expect(observer.observations).toEqual({})

            observer.observeResults([createResult('id1'), createResult('id1', false, 'error')])
            observer.observeAsyncFunctionResponses([createAsyncResponse('id1'), createAsyncResponse('id2', false)])

            expect(observer.observations).toMatchInlineSnapshot(`
                Object {
                  "id1": Object {
                    "asyncFunctionFailures": 0,
                    "asyncFunctionSuccesses": 1,
                    "failures": 1,
                    "successes": 1,
                    "timestamp": 1719229670000,
                  },
                  "id2": Object {
                    "asyncFunctionFailures": 1,
                    "asyncFunctionSuccesses": 0,
                    "failures": 0,
                    "successes": 0,
                    "timestamp": 1719229670000,
                  },
                }
            `)

            observer.observeAsyncFunctionResponses([createAsyncResponse('id2'), createAsyncResponse('id2')])

            expect(observer.observations).toMatchInlineSnapshot(`
                Object {
                  "id1": Object {
                    "asyncFunctionFailures": 0,
                    "asyncFunctionSuccesses": 1,
                    "failures": 1,
                    "successes": 1,
                    "timestamp": 1719229670000,
                  },
                  "id2": Object {
                    "asyncFunctionFailures": 1,
                    "asyncFunctionSuccesses": 2,
                    "failures": 0,
                    "successes": 0,
                    "timestamp": 1719229670000,
                  },
                }
            `)
        })
    })

    describe('deriveCurrentState', () => {
        let now: number
        let observations: HogWatcherObservationPeriod[]
        let states: HogWatcherStatePeriod[]

        beforeEach(() => {
            now = periodTimestamp()
            observations = []
            states = []

            jest.useFakeTimers()
            jest.setSystemTime(now)
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        const advanceTime = (ms: number) => {
            jest.advanceTimersByTime(ms)
        }

        const updateState = (ratings: number[], newStates: HogWatcherState[]) => {
            for (let i = 0; i < Math.max(ratings.length, newStates.length); i++) {
                advanceTime(OBSERVATION_PERIOD)

                if (newStates[i]) {
                    states.push({
                        timestamp: periodTimestamp(),
                        state: newStates[i],
                    })
                }

                if (typeof ratings[i] === 'number') {
                    observations.push({
                        // Simulate rating as ratio of success and failures
                        timestamp: Date.now(),
                        successes: 1000 * ratings[i],
                        failures: 1000 * (1 - ratings[i]),
                        asyncFunctionFailures: 0,
                        asyncFunctionSuccesses: 0,
                    })
                }
            }
        }

        const currentState = () => deriveCurrentState(observations, states)

        describe('1 - healthy', () => {
            it('should be healthy with no observations or previous states', () => {
                expect(currentState()).toBe(HogWatcherState.healthy)
            })

            it.each(Object.values(HogWatcherState))(
                'should be whatever the last state is (%s) if no observations',
                (lastState) => {
                    updateState([], [lastState as any])
                    expect(currentState()).toBe(lastState)
                }
            )

            it('should not change if too few observations', () => {
                updateState([0, 0], [])
                expect(getAverageRating(observations)).toEqual(0)
                expect(currentState()).toBe(HogWatcherState.healthy)
            })

            it('should move to overflow if enough observations are unhealthy', () => {
                updateState([1, 1, 0.8, 0.6, 0.6, 0.6, 0.6], [])
                expect(states).toMatchObject([])
                expect(getAverageRating(observations)).toBeLessThan(OVERFLOW_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.overflowed)
            })
        })

        describe('2 - overflow', () => {
            it('should stay in overflow if the rating does not change ', () => {
                updateState([1, 1, 0.8, 0.6, 0.6, 0.6, 0.6], [])
                expect(currentState()).toBe(HogWatcherState.overflowed)
                expect(getAverageRating(observations)).toBeLessThan(OVERFLOW_THRESHOLD)
                expect(getAverageRating(observations)).toBeGreaterThan(DISABLE_THRESHOLD)

                updateState([0.5, 0.5, 0.6, 0.7, 0.8, 1, 0.8], [])
                expect(getAverageRating(observations)).toBeLessThan(OVERFLOW_THRESHOLD)
                expect(getAverageRating(observations)).toBeGreaterThan(DISABLE_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.overflowed)
            })

            it('should move back to healthy with enough healthy activity ', () => {
                updateState([], [HogWatcherState.overflowed])
                expect(currentState()).toBe(HogWatcherState.overflowed)
                updateState([0.5, 0.8, 0.9, 0.9, 1, 0.9, 1], [])
                expect(getAverageRating(observations)).toBeGreaterThan(OVERFLOW_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.healthy)
            })

            it('should move to overflow if enough observations are unhealthy', () => {
                updateState([1, 1, 0.8, 0.6, 0.6, 0.6, 0.6], [])
                expect(states).toMatchObject([])
                expect(getAverageRating(observations)).toBeLessThan(OVERFLOW_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.overflowed)
            })

            it('should move to disabledForPeriod if sustained lower', () => {
                updateState([], [HogWatcherState.overflowed])
                expect(currentState()).toBe(HogWatcherState.overflowed)
                updateState([0.5, 0.4, 0.4, 0.2], [])
                expect(getAverageRating(observations)).toBeLessThan(DISABLE_THRESHOLD)
                expect(currentState()).toBe(HogWatcherState.disabledForPeriod)
            })

            it('should go to disabledIndefinitely with enough bad states', () => {
                updateState(
                    [],
                    [
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                        HogWatcherState.disabledForPeriod,
                        HogWatcherState.overflowed,
                    ]
                )
                expect(currentState()).toBe(HogWatcherState.overflowed)
                updateState([0.2, 0.2, 0.2, 0.2], [])
                expect(currentState()).toBe(HogWatcherState.disabledIndefinitely)
            })
        })

        describe('3 - disabledForPeriod', () => {
            it('should stay disabled for period until the period has passed ', () => {
                updateState([], [HogWatcherState.disabledForPeriod])
                expect(currentState()).toBe(HogWatcherState.disabledForPeriod)
                expect(states).toEqual([{ state: HogWatcherState.disabledForPeriod, timestamp: periodTimestamp() }])
                advanceTime(DISABLED_PERIOD - 1)
                expect(currentState()).toBe(HogWatcherState.disabledForPeriod)
                advanceTime(2)
                expect(currentState()).toBe(HogWatcherState.overflowed)
            })
        })

        describe('4 - disabledIndefinitely', () => {
            it('should stay in disabledIndefinitely no matter what', () => {
                updateState([], [HogWatcherState.disabledIndefinitely])

                expect(currentState()).toBe(HogWatcherState.disabledIndefinitely)
                // Technically this wouldn't be possible but still good to test
                updateState([1, 1, 1, 1, 1, 1, 1], [])
                expect(currentState()).toBe(HogWatcherState.disabledIndefinitely)
            })
        })
    })

    describe('integration', () => {
        let now: number
        let hub: Hub
        let closeHub: () => Promise<void>

        let watcher1: HogWatcher
        let watcher2: HogWatcher

        const advanceTime = (ms: number) => {
            now += ms
            console.log(`[TEST] Advancing time by ${ms}ms to ${now}`)
            mockNow.mockReturnValue(now)
        }

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub()

            now = 1720000000000
            mockNow.mockReturnValue(now)

            await deleteKeysWithPrefix(hub.redisPool, BASE_REDIS_KEY)

            watcher1 = new HogWatcher(hub)
            watcher2 = new HogWatcher(hub)
            await watcher1.start()
            await watcher2.start()
        })

        afterEach(async () => {
            await Promise.all([watcher1, watcher2].map((watcher) => watcher.stop()))
            jest.useRealTimers()
            await closeHub()
            jest.clearAllMocks()
        })

        describe('fetching', () => {
            it('should retrieve empty state', async () => {
                const res = await watcher1.fetchWatcher('id1')
                expect(res).toEqual({
                    observations: [],
                    rating: 1,
                    state: 1,
                    states: [],
                })
            })
        })

        describe('with observations', () => {
            it('should store observations', () => {
                watcher1.currentObservations.observeResults([createResult('id1'), createResult('id1', false, 'error')])
                watcher1.currentObservations.observeResults([createResult('id2'), createResult('id1')])
                watcher1.currentObservations.observeResults([createResult('id1')])

                expect(watcher1.currentObservations.observations).toMatchObject({
                    id1: {
                        failures: 1,
                        successes: 3,
                        timestamp: now,
                    },
                    id2: {
                        failures: 0,
                        successes: 1,
                        timestamp: now,
                    },
                })

                expect(watcher2.currentObservations.observations).toEqual({})
            })

            it('should sync nothing if still in period', async () => {
                watcher1.currentObservations.observeResults([createResult('id2'), createResult('id1')])

                expect(watcher1.observations).toEqual({})
                expect(watcher2.observations).toEqual({})
                await watcher1.sync()
                expect(watcher1.observations).toEqual({})
                expect(watcher2.observations).toEqual({})
            })

            it('should sync via redis pubsub once period changes', async () => {
                watcher1.currentObservations.observeResults([createResult('id2'), createResult('id1')])
                expect(watcher1.observations).toEqual({})
                await watcher1.sync()
                expect(watcher1.observations).toEqual({})
                advanceTime(OBSERVATION_PERIOD)

                const expectation = {
                    id1: [
                        {
                            failures: 0,
                            successes: 1,
                            timestamp: 1720000000000,
                        },
                    ],
                    id2: [
                        {
                            failures: 0,
                            successes: 1,
                            timestamp: 1720000000000,
                        },
                    ],
                }

                await watcher1.sync()
                expect(watcher1.observations).toMatchObject(expectation)
                await delay(100) // Allow pubsub to definitely have happenened
                expect(watcher2.observations).toMatchObject(expectation)
            })

            it('should also save the observations to redis', async () => {
                watcher1.currentObservations.observeResults([createResult('id2'), createResult('id1')])
                advanceTime(OBSERVATION_PERIOD)
                await watcher1.sync()
                const fromRedis = await watcher2.fetchWatcher('id1')
                expect(fromRedis).toMatchInlineSnapshot(`
                    Object {
                      "observations": Array [
                        Object {
                          "asyncFunctionFailures": 0,
                          "asyncFunctionSuccesses": 0,
                          "failures": 0,
                          "successes": 1,
                          "timestamp": 1720000000000,
                        },
                      ],
                      "rating": 1,
                      "state": 1,
                      "states": Array [],
                    }
                `)
            })

            it('should move the function into a bad state after enough periods', async () => {
                for (let i = 0; i < 4; i++) {
                    watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
                    advanceTime(OBSERVATION_PERIOD)
                    await watcher1.sync()
                }
                await delay(100)

                expect(watcher2.states['id1']).toEqual([
                    {
                        state: 2,
                        timestamp: 1720000030000, // After 3rd period it get evaluated
                    },
                    {
                        state: 3, // After 4th period it is bad enough to get temp disabled
                        timestamp: 1720000040000,
                    },
                ])

                advanceTime(DISABLED_PERIOD + 1)
                await watcher1.sync()
                await delay(100)
                expect(watcher2.states['id1']).toEqual([
                    {
                        state: 2,
                        timestamp: 1720000030000, // After 3rd period it get evaluated
                    },
                    {
                        state: 3, // After 4th period it is bad enough to get temp disabled
                        timestamp: 1720000040000,
                    },
                    {
                        state: 2,
                        timestamp: 1720000640000, // After enough time passing it is moved back to overflow
                    },
                ])
            })

            it('should save the states to redis so another watcher can grab it', async () => {
                for (let i = 0; i < 4; i++) {
                    watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
                    advanceTime(OBSERVATION_PERIOD)
                    await watcher1.sync()
                }
                await delay(100)
                const fromRedis = await watcher2.fetchWatcher('id1')
                expect(fromRedis).toMatchObject({
                    rating: 0,
                    state: 3,
                    states: [
                        {
                            state: 2,
                            timestamp: 1720000030000,
                        },
                        {
                            state: 3,
                            timestamp: 1720000040000,
                        },
                    ],
                })
            })

            it('should gather the observations of other watchers before saving', async () => {
                expect(watcher1.observations).toEqual({})
                for (let i = 0; i < 4; i++) {
                    // Create only bad on watcher1 and only good on watcher2
                    watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
                    watcher2.currentObservations.observeResults([
                        createResult('id1', true),
                        createResult('id1', true),
                        createResult('id1', true),
                    ])
                    advanceTime(OBSERVATION_PERIOD)
                    await watcher1.sync()
                    await watcher2.sync()
                }

                await delay(100)

                expect(watcher1.observations['id1']).toMatchObject([
                    {
                        failures: 1,
                        successes: 3,
                        timestamp: 1720000000000,
                    },
                    {
                        failures: 1,
                        successes: 3,
                        timestamp: 1720000010000,
                    },
                    {
                        failures: 1,
                        successes: 3,
                        timestamp: 1720000020000,
                    },
                    {
                        failures: 1,
                        successes: 3,
                        timestamp: 1720000030000,
                    },
                ])

                expect(watcher1.states['id1']).toMatchInlineSnapshot(`
                    Array [
                      Object {
                        "state": 2,
                        "timestamp": 1720000030000,
                      },
                    ]
                `)
            })

            it('should load existing states from redis', () => {
                expect(1).toEqual('NOT IMPLEMENTED')
            })
        })
    })
})
