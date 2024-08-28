jest.mock('../../src/utils/now', () => {
    return {
        now: jest.fn(() => Date.now()),
    }
})
import { BASE_REDIS_KEY, HogMasker } from '../../src/cdp/hog-masker'
import { CdpRedis, createCdpRedisPool } from '../../src/cdp/redis'
import { HogFunctionType } from '../../src/cdp/types'
import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { delay } from '../../src/utils/utils'
import { HOG_MASK_EXAMPLES } from './examples'
import { createHogExecutionGlobals, createHogFunction } from './fixtures'
import { deleteKeysWithPrefix } from './helpers/redis'

const mockNow: jest.Mock = require('../../src/utils/now').now as any

describe('HogMasker', () => {
    describe('integration', () => {
        let now: number
        let hub: Hub
        let closeHub: () => Promise<void>
        let masker: HogMasker
        let redis: CdpRedis

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub()

            now = 1720000000000
            mockNow.mockReturnValue(now)

            redis = createCdpRedisPool(hub)
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)

            masker = new HogMasker(redis)
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
            await closeHub()
            jest.clearAllMocks()
        })

        it('should return all functions without masks', async () => {
            const normalFunction = createHogFunction({})
            const invocations = [{ globals: createHogExecutionGlobals(), hogFunction: normalFunction }]
            const res = await masker.filterByMasking(invocations)

            expect(res.notMasked).toHaveLength(1)
            expect(res.masked).toEqual([])
        })

        it('should only allow one invocation call when masked for one function', async () => {
            const functionWithAllMasking = createHogFunction({
                ...HOG_MASK_EXAMPLES.all,
            })
            const globals1 = createHogExecutionGlobals({ event: { uuid: '1' } as any })
            const globals2 = createHogExecutionGlobals({ event: { uuid: '2' } as any })
            const globals3 = createHogExecutionGlobals({ event: { uuid: '3' } as any })
            const invocations = [
                { globals: globals1, hogFunction: functionWithAllMasking },
                { globals: globals2, hogFunction: functionWithAllMasking },
                { globals: globals3, hogFunction: functionWithAllMasking },
            ]

            const res = await masker.filterByMasking(invocations)
            expect(res.notMasked).toHaveLength(1)
            expect(res.masked).toHaveLength(2)
            expect(res.notMasked[0].globals).toEqual(globals1)
            expect(res.masked[0].globals).toEqual(globals2)
            expect(res.masked[1].globals).toEqual(globals3)

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
                { globals, hogFunction: functionWithAllMasking },
                { globals, hogFunction: functionWithAllMasking2 },
                { globals, hogFunction: functionWithNoMasking },
            ]

            const res = await masker.filterByMasking(invocations)
            expect(res.notMasked).toHaveLength(3)
            expect(res.masked).toHaveLength(0)

            const res2 = await masker.filterByMasking(invocations)
            expect(res2.notMasked).toHaveLength(1)
            expect(res2.masked).toHaveLength(2)
            expect(res2.notMasked[0].hogFunction).toEqual(functionWithNoMasking)
            expect(res2.masked[0].hogFunction).toEqual(functionWithAllMasking)
            expect(res2.masked[1].hogFunction).toEqual(functionWithAllMasking2)
        })

        describe('ttl', () => {
            let hogFunctionPerson: HogFunctionType
            let hogFunctionAll: HogFunctionType

            beforeEach(() => {
                hogFunctionPerson = createHogFunction({
                    masking: {
                        ...HOG_MASK_EXAMPLES.person.masking!,
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
                const invocations = [{ globals: createHogExecutionGlobals(), hogFunction: hogFunctionAll }]
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(1)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                await reallyAdvanceTime(1000)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(1)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
            })

            it('should mask with custom hog hash', async () => {
                const globalsPerson1 = createHogExecutionGlobals({ person: { uuid: '1' } as any })
                const globalsPerson2 = createHogExecutionGlobals({ person: { uuid: '2' } as any })

                const invocations = [
                    { globals: globalsPerson1, hogFunction: hogFunctionPerson },
                    { globals: globalsPerson1, hogFunction: hogFunctionAll },
                    { globals: globalsPerson2, hogFunction: hogFunctionPerson },
                    { globals: globalsPerson2, hogFunction: hogFunctionAll },
                ]
                const res = await masker.filterByMasking(invocations)
                expect(res.masked.length).toEqual(1)
                expect(res.notMasked.length).toEqual(3)
                const res2 = await masker.filterByMasking(invocations)
                expect(res2.masked.length).toEqual(4)
                expect(res2.notMasked.length).toEqual(0)
            })

            it('should mask until threshold passed', async () => {
                hogFunctionAll.masking!.threshold = 5

                const invocations = [{ globals: createHogExecutionGlobals(), hogFunction: hogFunctionAll }]
                // First one goes through
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(1)

                // Next 4 should be masked
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                // Now we have hit the threshold so it should not be masked
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(1)
                // Next 4 should be masked
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(0)
                // Again the Nth one shouldn't be masked
                expect((await masker.filterByMasking(invocations)).notMasked).toHaveLength(1)
            })

            it('should mask threshold based in a batch', async () => {
                hogFunctionAll.masking!.threshold = 5
                hogFunctionAll.masking!.ttl = 10

                // If we have 10 invocations in a batch then we should have 2 invocations that are not masked
                expect(
                    (
                        await masker.filterByMasking(
                            Array(10).fill({ globals: createHogExecutionGlobals(), hogFunction: hogFunctionAll })
                        )
                    ).notMasked
                ).toHaveLength(2)

                // Next one should cross the threshold
                expect(
                    (
                        await masker.filterByMasking([
                            { globals: createHogExecutionGlobals(), hogFunction: hogFunctionAll },
                        ])
                    ).notMasked
                ).toHaveLength(1)
            })
        })
    })
})
