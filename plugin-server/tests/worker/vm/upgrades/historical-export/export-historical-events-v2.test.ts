import { PluginMeta } from '@posthog/plugin-scaffold'
import deepmerge from 'deepmerge'

import { Hub, ISOTimestamp, PluginConfigVMInternalResponse } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'
import { createStorage } from '../../../../../src/worker/vm/extensions/storage'
import { createUtils } from '../../../../../src/worker/vm/extensions/utilities'
import {
    addHistoricalEventsExportCapabilityV2,
    EVENTS_PER_RUN,
    EXPORT_RUNNING_KEY,
    ExportHistoricalEventsJobPayload,
    ExportHistoricalEventsUpgradeV2,
    TestFunctions,
} from '../../../../../src/worker/vm/upgrades/historical-export/export-historical-events-v2'
import { fetchTimestampBoundariesForTeam } from '../../../../../src/worker/vm/upgrades/utils/utils'
import { pluginConfig39 } from '../../../../helpers/plugins'
import { resetTestDatabase } from '../../../../helpers/sql'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/worker/vm/upgrades/utils/utils')

describe('addHistoricalEventsExportCapabilityV2()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let vm: PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgradeV2>>

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
        hub.kafkaProducer.queueMessage = jest.fn()
        hub.kafkaProducer.flush = jest.fn()
    })

    afterAll(async () => {
        await hub.promiseManager.awaitPromisesIfNeeded()
        await closeHub()
    })

    function storage() {
        return createStorage(hub, pluginConfig39)
    }

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
                storage: storage(),
                utils: createUtils(hub, pluginConfig39.id),
                jobs: {
                    exportHistoricalEvents: jest.fn().mockReturnValue({ runNow: jest.fn() }),
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
            vm = addCapabilities()
            // @ts-expect-error testing-related schenanigans
            return vm.meta.global._testFunctions[name](...args)
        }
    }

    describe('coordinateHistoricExport()', () => {
        const coordinateHistoricExport = getTestMethod('coordinateHistoricExport')

        beforeEach(async () => {
            jest.spyOn(hub.db, 'queuePluginLogEntry')

            await resetTestDatabase()
        })

        it('does nothing if export isnt running / is done', async () => {
            await coordinateHistoricExport()

            expect(await storage().get('EXPORT_COORDINATION', null)).toEqual(null)
            expect(hub.db.queuePluginLogEntry).not.toHaveBeenCalled()
        })

        describe('export is running', () => {
            const params = {
                id: 1,
                parallelism: 3,
                dateFrom: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
                dateTo: '2021-11-01T05:00:00.000Z' as ISOTimestamp,
            }

            beforeEach(async () => {
                await storage().set(EXPORT_RUNNING_KEY, params)
            })

            it('logs progress of the export and does not start excessive jobs', async () => {
                await coordinateHistoricExport({
                    hasChanges: false,
                    exportIsDone: false,
                    progress: 0.7553,
                    done: [],
                    running: [],
                    toStartRunning: [],
                })

                expect(hub.db.queuePluginLogEntry).toHaveBeenCalledTimes(1)
                expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                    expect.objectContaining({
                        message: expect.stringContaining('Export progress: ■■■■■■■■■■■■■■■□□□□□ (75.5)%'),
                    })
                )

                expect(vm.meta.jobs.exportHistoricalEvents).not.toHaveBeenCalled()
                expect(await storage().get(EXPORT_RUNNING_KEY, null)).toEqual(params)
            })

            it('starts up new jobs and updates coordination data if needed', async () => {
                await coordinateHistoricExport({
                    hasChanges: true,
                    exportIsDone: false,
                    progress: 0.7553,
                    done: [
                        '2021-10-29T00:00:00.000Z',
                        '2021-10-30T00:00:00.000Z',
                        '2021-10-31T00:00:00.000Z',
                    ] as ISOTimestamp[],
                    running: ['2021-11-01T00:00:00.000Z'] as ISOTimestamp[],
                    toStartRunning: [['2021-11-01T00:00:00.000Z', '2021-11-01T05:00:00.000Z']] as Array<
                        [ISOTimestamp, ISOTimestamp]
                    >,
                })

                expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith({
                    endTime: 1635742800000,
                    exportId: 1,
                    fetchTimeInterval: 600000,
                    offset: 0,
                    retriesPerformedSoFar: 0,
                    startTime: 1635724800000,
                    timestampCursor: 1635724800000,
                })

                expect(await storage().get('EXPORT_COORDINATION', null)).toEqual({
                    done: ['2021-10-29T00:00:00.000Z', '2021-10-30T00:00:00.000Z', '2021-10-31T00:00:00.000Z'],
                    running: ['2021-11-01T00:00:00.000Z'],
                    progress: 0.7553,
                })
            })

            it('handles export being marked as done', async () => {
                await coordinateHistoricExport({
                    hasChanges: false,
                    exportIsDone: true,
                    progress: 1,
                    done: [],
                    running: [],
                    toStartRunning: [],
                })

                expect(hub.db.queuePluginLogEntry).toHaveBeenCalledTimes(1)
                expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                    expect.objectContaining({
                        message: expect.stringContaining('Done exporting all events!'),
                    })
                )
                expect(await storage().get(EXPORT_RUNNING_KEY, null)).toEqual(null)
            })
        })
    })

    describe('calculateCoordination()', () => {
        const calculateCoordination = getTestMethod('calculateCoordination')

        const params = {
            id: 1,
            parallelism: 3,
            dateFrom: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
            dateTo: '2021-11-01T05:00:00.000Z' as ISOTimestamp,
        }

        beforeEach(async () => {
            await resetTestDatabase()
        })

        it('does nothing if enough tasks running', async () => {
            const result = await calculateCoordination(params, [], [
                '2021-10-29T00:00:00.000Z',
                '2021-10-30T00:00:00.000Z',
                '2021-10-31T00:00:00.000Z',
            ] as ISOTimestamp[])

            expect(result).toEqual({
                hasChanges: false,
                done: [],
                running: ['2021-10-29T00:00:00.000Z', '2021-10-30T00:00:00.000Z', '2021-10-31T00:00:00.000Z'],
                toStartRunning: [],
                progress: 0,
                exportIsDone: false,
            })
        })

        it('kicks off new tasks if theres room', async () => {
            const result = await calculateCoordination(params, [], [])

            expect(result).toEqual({
                hasChanges: true,
                done: [],
                running: ['2021-10-29T00:00:00.000Z', '2021-10-30T00:00:00.000Z', '2021-10-31T00:00:00.000Z'],
                toStartRunning: [
                    ['2021-10-29T00:00:00.000Z', '2021-10-30T00:00:00.000Z'],
                    ['2021-10-30T00:00:00.000Z', '2021-10-31T00:00:00.000Z'],
                    ['2021-10-31T00:00:00.000Z', '2021-11-01T00:00:00.000Z'],
                ],
                progress: 0,
                exportIsDone: false,
            })
        })

        it('marks running tasks as done and counts progress', async () => {
            await storage().set('EXPORT_DATE_STATUS_2021-10-29T00:00:00.000Z', {
                done: false,
                progress: 0.5,
            })
            await storage().set('EXPORT_DATE_STATUS_2021-10-30T00:00:00.000Z', {
                done: true,
                progress: 1,
            })

            const result = await calculateCoordination(params, [], [
                '2021-10-29T00:00:00.000Z',
                '2021-10-30T00:00:00.000Z',
                '2021-10-31T00:00:00.000Z',
            ] as ISOTimestamp[])

            expect(result).toEqual({
                hasChanges: true,
                done: ['2021-10-30T00:00:00.000Z'],
                running: ['2021-10-29T00:00:00.000Z', '2021-10-31T00:00:00.000Z', '2021-11-01T00:00:00.000Z'],
                toStartRunning: [['2021-11-01T00:00:00.000Z', '2021-11-01T05:00:00.000Z']],
                progress: 0.375,
                exportIsDone: false,
            })
        })

        it('notifies if export is done after marking running tasks as done', async () => {
            await storage().set('EXPORT_DATE_STATUS_2021-10-30T00:00:00.000Z', {
                done: true,
                progress: 1,
            })

            const result = await calculateCoordination(
                params,
                ['2021-10-29T00:00:00.000Z', '2021-10-31T00:00:00.000Z', '2021-11-01T00:00:00.000Z'] as ISOTimestamp[],
                ['2021-10-30T00:00:00.000Z'] as ISOTimestamp[]
            )

            expect(result).toEqual({
                hasChanges: true,
                done: expect.arrayContaining([
                    '2021-10-29T00:00:00.000Z',
                    '2021-10-30T00:00:00.000Z',
                    '2021-10-31T00:00:00.000Z',
                    '2021-11-01T00:00:00.000Z',
                ]),
                running: [],
                toStartRunning: [],
                progress: 1,
                exportIsDone: true,
            })
        })
    })

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
