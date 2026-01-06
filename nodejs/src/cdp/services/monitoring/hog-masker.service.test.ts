import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { HogFlow } from '~/schema/hogflow'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { delay } from '~/utils/utils'

import { HOG_FLOW_MASK_EXAMPLES, HOG_MASK_EXAMPLES } from '../../_tests/examples'
import { createExampleInvocation, createHogExecutionGlobals, createHogFunction } from '../../_tests/fixtures'
import { createExampleHogFlowInvocation } from '../../_tests/fixtures-hogflows'
import { deleteKeysWithPrefix } from '../../_tests/redis'
import { CyclotronJobInvocationHogFunction, HogFunctionType } from '../../types'
import { BASE_REDIS_KEY, HogMaskerService } from './hog-masker.service'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

describe('HogMasker', () => {
    jest.retryTimes(3)
    describe('integration', () => {
        let now: number
        let hub: Hub
        let masker: HogMaskerService
        let redis: RedisV2

        beforeEach(async () => {
            hub = await createHub()
            now = 1720000000000
            mockNow.mockReturnValue(now)

            redis = createRedisV2PoolFromConfig({
                connection: hub.CDP_REDIS_HOST
                    ? {
                          url: hub.CDP_REDIS_HOST,
                          options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                      }
                    : { url: hub.REDIS_URL },
                poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
            })
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)

            masker = new HogMaskerService(redis)
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
            await closeHub(hub)
            jest.clearAllMocks()
        })

        it('should return all functions without masks', async () => {
            const normalFunction = createHogFunction({})
            const invocations = [createExampleInvocation(normalFunction)]
            const res = await masker.filterByMasking(invocations)

            expect(res.notMasked).toHaveLength(1)
            expect(res.masked).toEqual([])
        })

        it('supports hog flow invocations without trigger_masking', async () => {
            const hogFlow: HogFlow = {
                id: 'flow_1',
                team_id: 1,
                name: 'Test Flow',
                version: 1,
                actions: [],
                status: 'active',
                trigger: {
                    type: 'event',
                    filters: {
                        events: [],
                    },
                },
                trigger_masking: null,
                exit_condition: 'exit_only_at_end',
                edges: [],
            }
            const invocation = createExampleHogFlowInvocation(hogFlow)
            const res = await masker.filterByMasking([invocation])
            expect(res.notMasked).toHaveLength(1)
            expect(res.masked).toHaveLength(0)
        })

        it('should only allow one invocation call when masked for one function', async () => {
            const functionWithAllMasking = createHogFunction({
                ...HOG_MASK_EXAMPLES.all,
            })

            const invocation1 = createExampleInvocation(
                functionWithAllMasking,
                createHogExecutionGlobals({ event: { uuid: '1' } as any })
            )
            const invocation2 = createExampleInvocation(
                functionWithAllMasking,
                createHogExecutionGlobals({ event: { uuid: '2' } as any })
            )
            const invocation3 = createExampleInvocation(
                functionWithAllMasking,
                createHogExecutionGlobals({ event: { uuid: '3' } as any })
            )
            const invocations = [invocation1, invocation2, invocation3]

            const res = await masker.filterByMasking(invocations)
            expect(res.notMasked).toHaveLength(1)
            expect(res.masked).toHaveLength(2)
            expect(res.notMasked[0].state?.globals).toEqual(invocation1.state.globals)
            expect(res.masked[0].state?.globals).toEqual(invocation2.state.globals)
            expect(res.masked[1].state?.globals).toEqual(invocation3.state.globals)

            const res2 = await masker.filterByMasking(invocations)
            expect(res2.notMasked).toHaveLength(0)
            expect(res2.masked).toHaveLength(3)
        })

        it('allow multiple functions for the same globals', async () => {
            const functionWithAllMasking = createHogFunction({
                ...HOG_MASK_EXAMPLES.all,
            })
            const functionWithAllMasking2 = createHogFunction({
                ...HOG_MASK_EXAMPLES.all,
            })
            const functionWithNoMasking = createHogFunction({})
            const globals = createHogExecutionGlobals()
            const invocations = [
                createExampleInvocation(functionWithAllMasking, globals),
                createExampleInvocation(functionWithAllMasking2, globals),
                createExampleInvocation(functionWithNoMasking, globals),
            ]

            const res = await masker.filterByMasking(invocations)
            expect(res.notMasked).toHaveLength(3)
            expect(res.masked).toHaveLength(0)

            const res2 = await masker.filterByMasking(invocations)
            expect(res2.notMasked).toHaveLength(1)
            expect(res2.masked).toHaveLength(2)
            expect((res2.notMasked[0] as CyclotronJobInvocationHogFunction).hogFunction).toEqual(functionWithNoMasking)
            expect((res2.masked[0] as CyclotronJobInvocationHogFunction).hogFunction).toEqual(functionWithAllMasking)
            expect((res2.masked[1] as CyclotronJobInvocationHogFunction).hogFunction).toEqual(functionWithAllMasking2)
        })

        describe('ttl', () => {
            let hogFunctionPerson: HogFunctionType
            let hogFunctionAll: HogFunctionType
            let hogFunctionPersonAndEvent: HogFunctionType

            beforeEach(() => {
                hogFunctionPerson = createHogFunction({
                    masking: {
                        ...HOG_MASK_EXAMPLES.person.masking!,
                        ttl: 1,
                    },
                })

                hogFunctionPersonAndEvent = createHogFunction({
                    masking: {
                        ...HOG_MASK_EXAMPLES.personAndEvent.masking!,
                        ttl: 1,
                    },
                })

                hogFunctionAll = createHogFunction({
                    masking: {
                        ...HOG_MASK_EXAMPLES.all.masking!,
                        ttl: 1,
                    },
                })
            })
            it('should re-allow after the ttl expires', async () => {
                const invocations = [createExampleInvocation(hogFunctionAll)]
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(1)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                await reallyAdvanceTime(1000)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(1)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
            })

            it('should mask with custom hog hash', async () => {
                const globals1 = createHogExecutionGlobals({
                    person: { id: '1' } as any,
                    event: { event: '$pageview' } as any,
                })
                const globals2 = createHogExecutionGlobals({
                    person: { id: '2' } as any,
                    event: { event: '$autocapture' } as any,
                })
                const globals3 = createHogExecutionGlobals({
                    person: { id: '2' } as any,
                    event: { event: '$pageview' } as any,
                })

                const invocations = [
                    createExampleInvocation(hogFunctionPerson, globals1),
                    createExampleInvocation(hogFunctionAll, globals1),
                    createExampleInvocation(hogFunctionPersonAndEvent, globals1),
                    createExampleInvocation(hogFunctionPerson, globals2),
                    createExampleInvocation(hogFunctionAll, globals2),
                    createExampleInvocation(hogFunctionPersonAndEvent, globals2),
                    createExampleInvocation(hogFunctionPersonAndEvent, globals3),
                ]
                const res = await masker.filterByMasking(invocations)
                expect(res.masked.length).toEqual(1)
                expect(res.notMasked.length).toEqual(6)
                const res2 = await masker.filterByMasking(invocations)
                expect(res2.masked.length).toEqual(7)
                expect(res2.notMasked.length).toEqual(0)
            })

            it('should mask until threshold passed', async () => {
                hogFunctionAll.masking!.threshold = 5

                const invocation = createExampleInvocation(hogFunctionAll)
                // First one goes through
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(1)

                // Next 4 should be masked
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(0)
                // Now we have hit the threshold so it should not be masked
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(1)
                // Next 4 should be masked
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(0)
                // Again the Nth one shouldn't be masked
                expect((await masker.filterByMasking([invocation])).notMasked).toHaveLength(1)
            })

            it('should mask threshold based in a batch', async () => {
                hogFunctionAll.masking!.threshold = 5
                hogFunctionAll.masking!.ttl = 10

                // If we have 10 invocations in a batch then we should have 2 invocations that are not masked
                expect(
                    (await masker.filterByMasking(Array(10).fill(createExampleInvocation(hogFunctionAll)))).notMasked
                ).toHaveLength(2)

                // Next one should cross the threshold
                expect(
                    (await masker.filterByMasking([createExampleInvocation(hogFunctionAll)])).notMasked
                ).toHaveLength(1)
            })

            describe('ttl constraints', () => {
                const getRedisKeyTtl = async (): Promise<number> => {
                    const keys = await redis.useClient({ name: 'test-keys' }, async (client) => {
                        return await client.keys(`${BASE_REDIS_KEY}/mask/*`)
                    })
                    expect(keys?.length).toBe(1)
                    const ttl = await redis.useClient({ name: 'test-ttl' }, async (client) => {
                        return await client.ttl(keys![0])
                    })
                    return ttl!
                }

                const expectTtlNear = (ttl: number, expected: number) => {
                    expect(ttl).toBeLessThanOrEqual(expected)
                    expect(ttl).toBeGreaterThan(expected - 10)
                }

                const oneDaySeconds = 60 * 60 * 24
                const threeYearsSeconds = 60 * 60 * 24 * 365 * 3

                describe('hog functions', () => {
                    it('should default to 1 day when ttl is null', async () => {
                        const hogFunction = createHogFunction({
                            masking: {
                                ...HOG_MASK_EXAMPLES.all.masking!,
                                ttl: null,
                            },
                        })

                        await masker.filterByMasking([createExampleInvocation(hogFunction)])
                        expectTtlNear(await getRedisKeyTtl(), oneDaySeconds)
                    })

                    it('should cap at 1 day max', async () => {
                        const hogFunction = createHogFunction({
                            masking: {
                                ...HOG_MASK_EXAMPLES.all.masking!,
                                ttl: 60 * 60 * 24 * 365, // 1 year
                            },
                        })

                        await masker.filterByMasking([createExampleInvocation(hogFunction)])
                        expectTtlNear(await getRedisKeyTtl(), oneDaySeconds)
                    })
                })

                describe('hog flows', () => {
                    const createFlowWithTtl = (ttl: number | null): HogFlow => ({
                        id: `flow_${ttl}`,
                        team_id: 1,
                        name: 'Test Flow',
                        version: 1,
                        actions: [],
                        status: 'active',
                        trigger: {
                            type: 'event',
                            filters: {
                                events: [],
                            },
                        },
                        trigger_masking: {
                            ...HOG_FLOW_MASK_EXAMPLES.onceEver.trigger_masking!,
                            ttl,
                        },
                        exit_condition: 'exit_only_at_end',
                        edges: [],
                    })

                    it('should default to 3 years when ttl is null', async () => {
                        const hogFlow = createFlowWithTtl(null)
                        await masker.filterByMasking([createExampleHogFlowInvocation(hogFlow)])
                        expectTtlNear(await getRedisKeyTtl(), threeYearsSeconds)
                    })

                    it('should cap at 3 years when set to a higher value', async () => {
                        const hogFlow = createFlowWithTtl(60 * 60 * 24 * 365 * 10) // 10 years
                        await masker.filterByMasking([createExampleHogFlowInvocation(hogFlow)])
                        expectTtlNear(await getRedisKeyTtl(), threeYearsSeconds)
                    })
                })
            })

            describe('hog flow trigger masking', () => {
                let hogFlowEvery: HogFlow
                let hogFlowOncePer: HogFlow
                let hogFlowOnceEver: HogFlow

                beforeEach(() => {
                    const base: Partial<HogFlow> = {
                        team_id: 1,
                        name: 'Mask Flow',
                        version: 1,
                        actions: [],
                        status: 'active',
                        trigger: {
                            type: 'event',
                            filters: {
                                events: [],
                            },
                        },
                        exit_condition: 'exit_only_at_end',
                        edges: [],
                    }

                    hogFlowEvery = {
                        ...base,
                        id: 'hf_every',
                        trigger_masking: { ...HOG_FLOW_MASK_EXAMPLES.everyTime.trigger_masking },
                    } as HogFlow
                    hogFlowOncePer = {
                        ...base,
                        id: 'hf_once_per',
                        trigger_masking: { ...HOG_FLOW_MASK_EXAMPLES.oncePerTimePeriod.trigger_masking, ttl: 1 },
                    } as HogFlow
                    hogFlowOnceEver = {
                        ...base,
                        id: 'hf_once_ever',
                        trigger_masking: { ...HOG_FLOW_MASK_EXAMPLES.onceEver.trigger_masking },
                    } as HogFlow
                })

                it('allows only one hog flow invocation per masking hash per ttl', async () => {
                    const inv1 = createExampleHogFlowInvocation(hogFlowEvery)
                    const inv2 = createExampleHogFlowInvocation(hogFlowEvery)
                    const inv3 = createExampleHogFlowInvocation(hogFlowEvery)
                    const batch = [inv1, inv2, inv3]
                    const res = await masker.filterByMasking(batch)
                    expect(res.notMasked).toHaveLength(1)
                    expect(res.masked).toHaveLength(2)
                })

                it('resets after ttl for hog flow trigger masking', async () => {
                    const inv = createExampleHogFlowInvocation(hogFlowOncePer)
                    expect((await masker.filterByMasking([inv])).notMasked).toHaveLength(1)
                    expect((await masker.filterByMasking([inv])).masked).toHaveLength(1)
                    await reallyAdvanceTime(1000)
                    expect((await masker.filterByMasking([inv])).notMasked).toHaveLength(1)
                    expect((await masker.filterByMasking([inv])).masked).toHaveLength(1)
                })

                it('uses threshold for onceEver flow trigger masking', async () => {
                    const inv = createExampleHogFlowInvocation(hogFlowOnceEver)
                    expect((await masker.filterByMasking([inv])).notMasked).toHaveLength(1)
                    expect((await masker.filterByMasking([inv])).masked).toHaveLength(1)
                    expect((await masker.filterByMasking([inv])).masked).toHaveLength(1)
                })
            })
        })
    })
})
