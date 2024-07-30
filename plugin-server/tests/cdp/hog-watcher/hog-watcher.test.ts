jest.mock('../../../src/utils/now', () => {
    return {
        now: jest.fn(() => Date.now()),
    }
})

import { HogWatcher, HogWatcherActiveObservations } from '../../../src/cdp/hog-watcher/hog-watcher'
import { BASE_REDIS_KEY, runRedis } from '../../../src/cdp/hog-watcher/utils'
import { HogFunctionInvocationAsyncResponse, HogFunctionInvocationResult } from '../../../src/cdp/types'
import { defaultConfig } from '../../../src/config/config'
import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { delay } from '../../../src/utils/utils'
import { deleteKeysWithPrefix } from '../../helpers/redis'

const mockNow: jest.Mock = require('../../../src/utils/now').now as any

const createResult = (id: string, finished = true, error?: string): HogFunctionInvocationResult => {
    return {
        invocation: {
            id: 'invocation-id',
            teamId: 2,
            hogFunctionId: id,
            globals: {} as any,
            timings: [],
        },
        finished,
        error,
        logs: [],
    }
}

const createAsyncResponse = (id: string, success = true): HogFunctionInvocationAsyncResponse => {
    return {
        state: '',
        teamId: 2,
        hogFunctionId: id,
        asyncFunctionResponse: {
            error: !success ? 'error' : null,
            response: {},
        },
    }
}

const config = defaultConfig

describe('HogWatcher', () => {
    describe('HogWatcherActiveObservations', () => {
        let observer: HogWatcherActiveObservations

        beforeEach(() => {
            observer = new HogWatcherActiveObservations(config)
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

    describe('integration', () => {
        let now: number
        let hub: Hub
        let closeHub: () => Promise<void>

        let watcher1: HogWatcher
        let watcher2: HogWatcher

        const advanceTime = (ms: number) => {
            now += ms
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

        it('should retrieve empty state', async () => {
            const res = await watcher1.fetchWatcher('id1')
            expect(res).toEqual({
                ratings: [],
                state: 1,
                states: [],
            })
        })

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
            expect(watcher1.currentObservations.observations).not.toEqual({})
            await watcher1.sync()
            expect(watcher1.currentObservations.observations).not.toEqual({})
            expect(await watcher2.fetchState()).toEqual({
                observations: {},
                ratings: {},
                states: {},
            })
        })

        it('should persist the in flight observations to redis', async () => {
            watcher1.currentObservations.observeResults([createResult('id2'), createResult('id1')])
            advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
            await watcher1.sync()
            expect(watcher1.currentObservations.observations).toEqual({})
            const persistedState = await watcher2.fetchState()
            expect(persistedState).toMatchObject({
                observations: {
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
                },
            })
        })

        it('should save the states and ratings to redis if enough periods passed', async () => {
            watcher1.currentObservations.observeResults([createResult('id2'), createResult('id1')])
            watcher2.currentObservations.observeResults([
                createResult('id2', false, 'error'),
                createResult('id1', true),
            ])

            let expectation: any = {
                observations: {
                    id1: [expect.any(Object), expect.any(Object)],
                    id2: [expect.any(Object), expect.any(Object)],
                },
                ratings: {},
                states: {},
            }

            // Move forward one period - this passes themasking period, ensuring that the observations are persisted
            advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
            await watcher1.sync()
            await watcher2.sync()
            await delay(100) // Allow pubsub to happen
            expect(watcher2.states).toEqual({})
            // Watcher1 should be leader and have the globalState
            expect(watcher1.globalState).toEqual(expectation)
            expect(watcher2.globalState).toEqual(undefined)
            expect(await watcher2.fetchState()).toEqual(expectation)

            // Move forward one final period and the initial observations should now be ratings
            advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
            await watcher1.sync()
            await watcher2.sync()
            await delay(100) // Allow pubsub to happen

            expectation = {
                observations: {},
                ratings: {
                    id1: [{ rating: 1, timestamp: 1720000000000 }],
                    id2: [{ rating: 0.5, timestamp: 1720000000000 }],
                },
                states: {},
            }

            expect(watcher2.states).toEqual({}) // No states yet as everything is healthy
            expect(watcher1.globalState).toEqual(expectation)
            // Persisted state should match the global state
            expect(await watcher2.fetchState()).toEqual(expectation)
        })

        it('should move the function into a bad state after enough periods', async () => {
            // We need to move N times forward to get past the masking period and have enough ratings to make a decision
            // 2 for the persistance of the ratings, 3 more for the evaluation, 3 more for the subsequent evaluation
            for (let i = 0; i < 2 + 3 + 3; i++) {
                watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
                advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
                await watcher1.sync()
            }
            await delay(100)

            expect(watcher1.globalState).toMatchObject({
                observations: {},
                ratings: {
                    id1: Array(7)
                        .fill(0)
                        .map((_, i) => ({
                            rating: 0,
                            timestamp: 1720000000000 + i * config.CDP_WATCHER_OBSERVATION_PERIOD,
                        })),
                },
                states: {
                    id1: [
                        {
                            state: 2,
                            timestamp: 1720000040000,
                        },
                        {
                            state: 3,
                            timestamp: 1720000080000,
                        },
                    ],
                },
            })

            expect(watcher2.states['id1']).toEqual(3)

            advanceTime(config.CDP_WATCHER_DISABLED_PERIOD + 1)
            await watcher1.sync()
            await delay(100)
            expect(watcher2.states['id1']).toEqual(2)
        })

        it('should save the states to redis so another watcher can grab it', async () => {
            for (let i = 0; i < 5; i++) {
                watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
                advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
                await watcher1.sync()
            }
            await delay(100)

            expect(await watcher2.fetchWatcher('id1')).toMatchObject({
                state: 2,
                states: [
                    {
                        state: 2,
                        timestamp: 1720000040000,
                    },
                ],
            })
        })

        it('should load existing states from redis', async () => {
            for (let i = 0; i < 5; i++) {
                watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
                advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
                await watcher1.sync()
            }

            const newWatcher = new HogWatcher(hub)
            await newWatcher.start()
            expect(newWatcher.states).toEqual({
                id1: 2,
            })
        })

        it('should react to becoming or losing leader status', async () => {
            watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
            advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
            await watcher1.sync()
            const stateExpectation = {
                observations: { id1: [expect.any(Object)] },
                ratings: {},
                states: {},
            }
            expect(watcher1.isLeader).toEqual(true)
            expect(watcher1.globalState).toEqual(stateExpectation)
            expect(watcher2.isLeader).toEqual(false)
            expect(watcher2.globalState).toEqual(undefined)

            // Simulate the ttl running out
            await runRedis(hub.redisPool, 'test', (client) => client.del(BASE_REDIS_KEY + '/leader'))

            // Watcher 2 goes first so will grab leadership
            await Promise.all([watcher2.sync(), watcher1.sync()])
            expect(watcher1.isLeader).toEqual(false)
            expect(watcher1.globalState).toEqual(undefined)
            expect(watcher2.isLeader).toEqual(true)
            expect(watcher2.globalState).toEqual(stateExpectation)
        })

        it('should move a problematic function in and out of overflow until eventually disabled', async () => {
            // NOTE: The length here just happens be the right loop count to

            let maxLoops = 100
            while (watcher1.getFunctionState('id1') !== 4 && maxLoops > 0) {
                maxLoops--
                if (watcher1.getFunctionState('id1') < 3) {
                    // If we are anything other than disables, simulate a bad invocations
                    watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
                    advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
                } else {
                    // Skip ahead if the function is disabled
                    advanceTime(config.CDP_WATCHER_DISABLED_PERIOD)
                }
                await watcher1.sync()
                await delay(5)
            }

            const states = watcher1.globalState?.states['id1'] ?? []
            const duration = Math.round((states[states.length - 1]!.timestamp - states[0]!.timestamp) / 1000 / 60)
            // Little helper check to remind us the total time for a bad function to get to be permanently disabled
            expect(`Time to fully disable: ${duration}mins`).toMatchInlineSnapshot(`"Time to fully disable: 63mins"`)

            expect(states).toMatchInlineSnapshot(`
                    Array [
                      Object {
                        "state": 2,
                        "timestamp": 1720000040000,
                      },
                      Object {
                        "state": 3,
                        "timestamp": 1720000080000,
                      },
                      Object {
                        "state": 2,
                        "timestamp": 1720001280000,
                      },
                      Object {
                        "state": 3,
                        "timestamp": 1720001320000,
                      },
                      Object {
                        "state": 2,
                        "timestamp": 1720002520000,
                      },
                      Object {
                        "state": 3,
                        "timestamp": 1720002560000,
                      },
                      Object {
                        "state": 2,
                        "timestamp": 1720003760000,
                      },
                      Object {
                        "state": 4,
                        "timestamp": 1720003800000,
                      },
                    ]
                `)
        })

        it('should react to incoming manual state changes', async () => {
            await watcher1.forceStateChange('id1', 2)
            await delay(100)

            const stateExpectation = {
                observations: {},
                ratings: {},
                states: {
                    id1: [
                        {
                            state: 2,
                            timestamp: 1720000000000,
                        },
                    ],
                },
            }
            expect(watcher1.isLeader).toEqual(true)
            expect(watcher1.globalState).toEqual(stateExpectation)
            expect(watcher2.isLeader).toEqual(false)
            expect(watcher2.globalState).toEqual(undefined)
        })
    })
})
