import { BASE_REDIS_KEY, HogWatcher } from '../../src/cdp/hog-watcher'
import { HogFunctionInvocationResult } from '../../src/cdp/types'
import { defaultConfig } from '../../src/config/config'
import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { deleteKeysWithPrefix } from '../helpers/redis'

const config = defaultConfig

const createResult = (options: {
    id: string
    duration?: number
    finished?: boolean
    error?: string
}): HogFunctionInvocationResult => {
    return {
        invocation: {
            id: 'invocation-id',
            teamId: 2,
            hogFunctionId: options.id,
            globals: {} as any,
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
        let hub: Hub
        let closeHub: () => Promise<void>
        let watcher: HogWatcher

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub()

            await deleteKeysWithPrefix(hub.redisPool, BASE_REDIS_KEY)

            watcher = new HogWatcher(hub)
        })

        afterEach(async () => {
            jest.useRealTimers()
            await closeHub()
            jest.clearAllMocks()
        })

        it('should retrieve empty state', async () => {
            const res = await watcher.getStates(['id1', 'id2'])
            expect(res).toEqual({
                id1: { rating: 0, state: 1 },
                id2: { rating: 0, state: 1 },
            })
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
                { cost: 24, state: 1 },
                [
                    createResult({ id: 'id1', duration: 1000 }),
                    createResult({ id: 'id1', duration: 1000 }),
                    createResult({ id: 'id1', duration: 1000 }),
                ],
            ],
            // [{ tokens: 0, state: 1 }, [createResult({ id: 'id1', duration: 5000 })]],
            // [{ tokens: -10, state: 1 }, [createResult({ id: 'id1', duration: 10000 })]],
            // [
            //     { tokens: -41, state: 1 },
            //     [
            //         createResult({ id: 'id1', duration: 5000 }),
            //         createResult({ id: 'id1', duration: 10000 }),
            //         createResult({ id: 'id1', duration: 20000 }),
            //     ],
            // ],

            // [{ tokens: -10, state: 1 }, [createResult({ id: 'id1', error: 'errored!' })]],
        ]

        it.each(cases)('should update tokens based on results %s %s', async (expectedScore, results) => {
            await watcher.observeResults(results)
            expect(await watcher.getStates(['id1'])).toMatchObject({
                id1: {
                    tokens: config.CDP_WATCHER_BUCKET_SIZE - expectedScore.cost,
                    state: expectedScore.state,
                },
            })
        })

        it('should max out scores', async () => {
            let lotsOfResults = Array(10000).fill(createResult({ id: 'id1', error: 'error!' }))

            await watcher.observeResults(lotsOfResults)

            expect(await watcher.getStates(['id1'])).toMatchObject({
                id1: { tokens: 0, state: 3 },
            })

            lotsOfResults = Array(10000).fill(createResult({ id: 'id2' }))

            await watcher.observeResults(lotsOfResults)

            expect(await watcher.getStates(['id2'])).toMatchObject({
                id2: { tokens: 0, state: 1 },
            })
        })

        // it('should move the function into a bad state after enough periods', async () => {
        //     // We need to move N times forward to get past the masking period and have enough tokenss to make a decision
        //     // 2 for the persistance of the ratings, 3 more for the evaluation, 3 more for the subsequent evaluation
        //     for (let i = 0; i < 2 + 3 + 3; i++) {
        //         watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
        //         advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
        //         await watcher1.sync()
        //     }
        //     await delay(100)

        //     expect(watcher1.globalState).toMatchObject({
        //         observations: {},
        //         ratings: {
        //             id1: Array(7)
        //                 .fill(0)
        //                 .map((_, i) => ({
        //                     rating: 0,
        //                     timestamp: 1720000000000 + i * config.CDP_WATCHER_OBSERVATION_PERIOD,
        //                 })),
        //         },
        //         states: {
        //             id1: [
        //                 {
        //                     state: 2,
        //                     timestamp: 1720000040000,
        //                 },
        //                 {
        //                     state: 3,
        //                     timestamp: 1720000080000,
        //                 },
        //             ],
        //         },
        //     })

        //     expect(watcher2.states['id1']).toEqual(3)

        //     advanceTime(config.CDP_WATCHER_DISABLED_PERIOD + 1)
        //     await watcher1.sync()
        //     await delay(100)
        //     expect(watcher2.states['id1']).toEqual(2)
        // })

        // it('should save the states to redis so another watcher can grab it', async () => {
        //     for (let i = 0; i < 5; i++) {
        //         watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
        //         advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
        //         await watcher1.sync()
        //     }
        //     await delay(100)

        //     expect(await watcher2.fetchWatcher('id1')).toMatchObject({
        //         state: 2,
        //         states: [
        //             {
        //                 state: 2,
        //                 timestamp: 1720000040000,
        //             },
        //         ],
        //     })
        // })

        // it('should load existing states from redis', async () => {
        //     for (let i = 0; i < 5; i++) {
        //         watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
        //         advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
        //         await watcher1.sync()
        //     }

        //     const newWatcher = new HogWatcher(hub)
        //     await newWatcher.start()
        //     expect(newWatcher.states).toEqual({
        //         id1: 2,
        //     })
        // })

        // it('should react to becoming or losing leader status', async () => {
        //     watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
        //     advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
        //     await watcher1.sync()
        //     const stateExpectation = {
        //         observations: { id1: [expect.any(Object)] },
        //         ratings: {},
        //         states: {},
        //     }
        //     expect(watcher1.isLeader).toEqual(true)
        //     expect(watcher1.globalState).toEqual(stateExpectation)
        //     expect(watcher2.isLeader).toEqual(false)
        //     expect(watcher2.globalState).toEqual(undefined)

        //     // Simulate the ttl running out
        //     await runRedis(hub.redisPool, 'test', (client) => client.del(BASE_REDIS_KEY + '/leader'))

        //     // Watcher 2 goes first so will grab leadership
        //     await Promise.all([watcher2.sync(), watcher1.sync()])
        //     expect(watcher1.isLeader).toEqual(false)
        //     expect(watcher1.globalState).toEqual(undefined)
        //     expect(watcher2.isLeader).toEqual(true)
        //     expect(watcher2.globalState).toEqual(stateExpectation)
        // })

        // it('should move a problematic function in and out of overflow until eventually disabled', async () => {
        //     // NOTE: The length here just happens be the right loop count to

        //     let maxLoops = 100
        //     while (watcher1.getFunctionState('id1') !== 4 && maxLoops > 0) {
        //         maxLoops--
        //         if (watcher1.getFunctionState('id1') < 3) {
        //             // If we are anything other than disables, simulate a bad invocations
        //             watcher1.currentObservations.observeResults([createResult('id1', false, 'error')])
        //             advanceTime(config.CDP_WATCHER_OBSERVATION_PERIOD)
        //         } else {
        //             // Skip ahead if the function is disabled
        //             advanceTime(config.CDP_WATCHER_DISABLED_PERIOD)
        //         }
        //         await watcher1.sync()
        //         await delay(5)
        //     }

        //     const states = watcher1.globalState?.states['id1'] ?? []
        //     const duration = Math.round((states[states.length - 1]!.timestamp - states[0]!.timestamp) / 1000 / 60)
        //     // Little helper check to remind us the total time for a bad function to get to be permanently disabled
        //     expect(`Time to fully disable: ${duration}mins`).toMatchInlineSnapshot(`"Time to fully disable: 63mins"`)

        //     expect(states).toMatchInlineSnapshot(`
        //             Array [
        //               Object {
        //                 "state": 2,
        //                 "timestamp": 1720000040000,
        //               },
        //               Object {
        //                 "state": 3,
        //                 "timestamp": 1720000080000,
        //               },
        //               Object {
        //                 "state": 2,
        //                 "timestamp": 1720001280000,
        //               },
        //               Object {
        //                 "state": 3,
        //                 "timestamp": 1720001320000,
        //               },
        //               Object {
        //                 "state": 2,
        //                 "timestamp": 1720002520000,
        //               },
        //               Object {
        //                 "state": 3,
        //                 "timestamp": 1720002560000,
        //               },
        //               Object {
        //                 "state": 2,
        //                 "timestamp": 1720003760000,
        //               },
        //               Object {
        //                 "state": 4,
        //                 "timestamp": 1720003800000,
        //               },
        //             ]
        //         `)
        // })

        // it('should react to incoming manual state changes', async () => {
        //     await watcher1.forceStateChange('id1', 2)
        //     await delay(100)

        //     const stateExpectation = {
        //         observations: {},
        //         ratings: {},
        //         states: {
        //             id1: [
        //                 {
        //                     state: 2,
        //                     timestamp: 1720000000000,
        //                 },
        //             ],
        //         },
        //     }
        //     expect(watcher1.isLeader).toEqual(true)
        //     expect(watcher1.globalState).toEqual(stateExpectation)
        //     expect(watcher2.isLeader).toEqual(false)
        //     expect(watcher2.globalState).toEqual(undefined)
        // })
    })
})
