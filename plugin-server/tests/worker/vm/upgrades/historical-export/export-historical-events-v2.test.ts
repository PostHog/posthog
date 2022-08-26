import { PluginMeta } from '@posthog/plugin-scaffold'
import deepmerge from 'deepmerge'

import { Hub, ISOTimestamp, PluginConfigVMInternalResponse } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'
import { createStorage } from '../../../../../src/worker/vm/extensions/storage'
import { createUtils } from '../../../../../src/worker/vm/extensions/utilities'
import {
    addHistoricalEventsExportCapabilityV2,
    EVENTS_PER_RUN,
    ExportHistoricalEventsJobPayload,
    ExportHistoricalEventsUpgradeV2,
    TestFunctions,
} from '../../../../../src/worker/vm/upgrades/historical-export/export-historical-events-v2'
import { fetchTimestampBoundariesForTeam } from '../../../../../src/worker/vm/upgrades/utils/utils'
import { pluginConfig39 } from '../../../../helpers/plugins'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/worker/vm/upgrades/utils/utils')

describe('addHistoricalEventsExportCapabilityV2()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterAll(async () => {
        await hub.kafkaProducer.flush()
        await closeHub()
    })

    function addCapabilities(overrides?: any) {
        const mockVM = deepmerge(overrides, {
            methods: {
                exportEvents: jest.fn(),
            },
            tasks: {
                schedule: {},
                job: {},
            },
            meta: {
                storage: createStorage(hub, pluginConfig39),
                utils: createUtils(hub, pluginConfig39.id),
                jobs: {
                    exportHistoricalEvents: jest.fn().mockReturnValue(jest.fn()),
                },
                global: {},
            },
        }) as unknown as PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgradeV2>>

        addHistoricalEventsExportCapabilityV2(hub, pluginConfig39, mockVM)

        return mockVM
    }

    function getTestMethod<T extends keyof TestFunctions>(name: T): TestFunctions[T] {
        // @ts-expect-error testing-related schenanigans
        return (...args: any[]) => {
            const vm = addCapabilities()
            // @ts-expect-error testing-related schenanigans
            return vm.meta.global._testFunctions[name](...args)
        }
    }

    describe('nextFetchTimeInterval()', () => {
        const nextFetchTimeInterval = getTestMethod('nextFetchTimeInterval')

        const ONE_HOUR = 1000 * 60 * 60
        const defaultPayload: ExportHistoricalEventsJobPayload = {
            timestampCursor: 0,
            startTime: 0,
            endTime: 1000,
            offset: 0,
            retriesPerformedSoFar: 0,
            exportId: 0,
            fetchTimeInterval: ONE_HOUR,
        }

        it('returns existing fetchTimeInterval if more in current time range', () => {
            expect(nextFetchTimeInterval(defaultPayload, EVENTS_PER_RUN)).toEqual(ONE_HOUR)
        })

        it('returns existing fetchTimeInterval if more in current time range on a late page', () => {
            expect(nextFetchTimeInterval({ ...defaultPayload, offset: 5 * EVENTS_PER_RUN }, EVENTS_PER_RUN)).toEqual(
                ONE_HOUR
            )
        })

        it('returns existing fetchTimeInterval if time range mostly full', () => {
            expect(nextFetchTimeInterval(defaultPayload, EVENTS_PER_RUN * 0.9)).toEqual(ONE_HOUR)
        })

        it('increases fetchTimeInterval if time range mostly empty', () => {
            expect(nextFetchTimeInterval(defaultPayload, EVENTS_PER_RUN * 0.1)).toEqual(ONE_HOUR * 1.2)
        })

        it('decreases fetchTimeInterval if on a late page and no more to fetch', () => {
            expect(nextFetchTimeInterval({ ...defaultPayload, offset: 5 * EVENTS_PER_RUN }, 10)).toEqual(ONE_HOUR / 1.2)
        })
    })

    describe('getTimestampBoundaries()', () => {
        const getTimestampBoundaries = getTestMethod('getTimestampBoundaries')

        it('returns timestamp boundaries passed into interface job', async () => {
            expect(
                await getTimestampBoundaries({
                    dateFrom: '2021-10-29T00:00:00.000Z',
                    dateTo: '2021-11-29T00:00:00.000Z',
                })
            ).toEqual({
                min: new Date('2021-10-29T00:00:00.000Z'),
                max: new Date('2021-11-29T00:00:00.000Z'),
            })

            expect(fetchTimestampBoundariesForTeam).not.toHaveBeenCalled()
        })

        it('raises an error for invalid timestamp formats', async () => {
            await expect(
                getTimestampBoundaries({
                    dateFrom: 'afaffaf',
                    dateTo: 'efg',
                })
            ).rejects.toThrowError("'dateFrom' and 'dateTo' should be timestamps in ISO string format.")
        })

        it('returns timestamp boundaries fetched from clickhouse if none passed from interface', async () => {
            jest.mocked(fetchTimestampBoundariesForTeam).mockResolvedValue({
                min: new Date('2021-10-29T00:00:00.000Z'),
                max: new Date('2022-10-29T00:00:00.000Z'),
            })

            expect(await getTimestampBoundaries({})).toEqual({
                min: new Date('2021-10-29T00:00:00.000Z'),
                max: new Date('2022-10-29T00:00:00.000Z'),
            })
        })

        it('raises an error if neither can be resolved', async () => {
            jest.mocked(fetchTimestampBoundariesForTeam).mockResolvedValue(null)

            await expect(getTimestampBoundaries({})).rejects.toThrowError(
                `Unable to determine the timestamp bound for the export automatically. Please specify 'dateFrom'/'dateTo' values.`
            )
        })
    })

    describe('getExportDateRange()', () => {
        const getExportDateRange = getTestMethod('getExportDateRange')

        it('returns values in range from start of the date', () => {
            expect(
                getExportDateRange({
                    id: 1,
                    parallelism: 1,
                    dateFrom: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
                    dateTo: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
                })
            ).toEqual([])

            expect(
                getExportDateRange({
                    id: 1,
                    parallelism: 1,
                    dateFrom: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
                    dateTo: '2021-11-02T00:00:00.000Z' as ISOTimestamp,
                })
            ).toEqual([
                ['2021-10-29T00:00:00.000Z', '2021-10-30T00:00:00.000Z'],
                ['2021-10-30T00:00:00.000Z', '2021-10-31T00:00:00.000Z'],
                ['2021-10-31T00:00:00.000Z', '2021-11-01T00:00:00.000Z'],
                ['2021-11-01T00:00:00.000Z', '2021-11-02T00:00:00.000Z'],
            ])
        })

        it('handles partial-day ranges gracefully', () => {
            expect(
                getExportDateRange({
                    id: 1,
                    parallelism: 1,
                    dateFrom: '2021-10-29T01:00:00.000Z' as ISOTimestamp,
                    dateTo: '2021-10-30T05:55:00.000Z' as ISOTimestamp,
                })
            ).toEqual([
                ['2021-10-29T01:00:00.000Z', '2021-10-30T00:00:00.000Z'],
                ['2021-10-30T00:00:00.000Z', '2021-10-30T05:55:00.000Z'],
            ])
        })
    })

    describe('progressBar()', () => {
        const progressBar = getTestMethod('progressBar')

        it('calculates progress correctly', () => {
            expect(progressBar(0)).toEqual('□□□□□□□□□□□□□□□□□□□□')
            expect(progressBar(1)).toEqual('■■■■■■■■■■■■■■■■■■■■')
            expect(progressBar(0.5)).toEqual('■■■■■■■■■■□□□□□□□□□□')
            expect(progressBar(0.7)).toEqual('■■■■■■■■■■■■■■□□□□□□')
            expect(progressBar(0.12)).toEqual('■■□□□□□□□□□□□□□□□□□□')
            expect(progressBar(0.12, 10)).toEqual('■□□□□□□□□□')
        })
    })
})
