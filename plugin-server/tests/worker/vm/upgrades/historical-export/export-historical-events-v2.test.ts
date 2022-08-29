import { PluginMeta, RetryError } from '@posthog/plugin-scaffold'

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
import {
    fetchEventsForInterval,
    fetchTimestampBoundariesForTeam,
} from '../../../../../src/worker/vm/upgrades/utils/utils'
import { pluginConfig39 } from '../../../../helpers/plugins'
import { resetTestDatabase } from '../../../../helpers/sql'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/worker/vm/upgrades/utils/utils')

const ONE_HOUR = 1000 * 60 * 60

describe('addHistoricalEventsExportCapabilityV2()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let vm: PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgradeV2>>
    let runNow: jest.Mock, runIn: jest.Mock

    beforeEach(() => {
        // eslint-disable-next-line @typescript-eslint/ban-ts-comment
        // @ts-expect-error
        vm = undefined
    })

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
        hub.kafkaProducer.queueMessage = jest.fn()
        hub.kafkaProducer.flush = jest.fn()
        jest.spyOn(hub.db, 'queuePluginLogEntry')

        jest.spyOn(Date, 'now').mockReturnValue(1_000_000_000)
    })

    afterAll(async () => {
        await hub.promiseManager.awaitPromisesIfNeeded()
        await closeHub()
    })

    function storage() {
        return createStorage(hub, pluginConfig39)
    }

    function createVM() {
        runIn = jest.fn()
        runNow = jest.fn()
        // :TODO: Kill deepmerge
        const mockVM = {
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
                    exportHistoricalEvents: jest.fn().mockReturnValue({ runNow, runIn }),
                },
                global: {},
            },
        } as unknown as PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgradeV2>>

        addHistoricalEventsExportCapabilityV2(hub, pluginConfig39, mockVM)

        vm = mockVM
    }

    function getTestMethod<T extends keyof TestFunctions>(name: T): TestFunctions[T] {
        // @ts-expect-error testing-related schenanigans
        return (...args: any[]) => {
            if (!vm) {
                createVM()
            }
            // @ts-expect-error testing-related schenanigans
            return vm.meta.global._testFunctions[name](...args)
        }
    }

    describe('exportHistoricalEvents()', () => {
        const exportHistoricalEvents = getTestMethod('exportHistoricalEvents')

        const defaultPayload: ExportHistoricalEventsJobPayload = {
            timestampCursor: 1635724800000,
            startTime: 1635724800000,
            endTime: 1635742800000,
            exportId: 1,
            fetchTimeInterval: ONE_HOUR,
            offset: 0,
            retriesPerformedSoFar: 0,
            statusKey: 'statusKey',
        }

        beforeEach(async () => {
            await storage().set(EXPORT_RUNNING_KEY, {
                id: 1,
                parallelism: 3,
                dateFrom: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
                dateTo: '2021-11-01T05:00:00.000Z' as ISOTimestamp,
            })
        })

        it('stores current progress in storage under `statusKey`', async () => {
            jest.mocked(fetchEventsForInterval).mockResolvedValue([])

            await exportHistoricalEvents({ ...defaultPayload, timestampCursor: 1635730000000 })

            expect(await storage().get('statusKey', null)).toEqual({
                ...defaultPayload,
                timestampCursor: 1635730000000,
                done: false,
                progress: expect.closeTo(0.28888),
                statusTime: Date.now(),
            })
        })

        it('logs and marks part of export done if reached the end', async () => {
            await exportHistoricalEvents({ ...defaultPayload, timestampCursor: defaultPayload.endTime })

            expect(fetchEventsForInterval).not.toHaveBeenCalled()
            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'Finished processing events from 2021-11-01T00:00:00.000Z to 2021-11-01T05:00:00.000Z'
                    ),
                })
            )
            expect(await storage().get('statusKey', null)).toEqual({
                ...defaultPayload,
                timestampCursor: defaultPayload.endTime,
                done: true,
                progress: 1,
                statusTime: Date.now(),
            })
        })

        it('calls exportEvents and logs with fetched events', async () => {
            jest.mocked(fetchEventsForInterval).mockResolvedValue([1, 2, 3])

            await exportHistoricalEvents(defaultPayload)

            expect(vm.methods.exportEvents).toHaveBeenCalledWith([1, 2, 3])
            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'Successfully processed events 0-3 from 2021-11-01T00:00:00.000Z to 2021-11-01T01:00:00.000Z.'
                    ),
                })
            )
        })

        it('does not call exportEvents or log if no events in time range', async () => {
            jest.mocked(fetchEventsForInterval).mockResolvedValue([])

            await exportHistoricalEvents(defaultPayload)

            expect(vm.methods.exportEvents).not.toHaveBeenCalled()
            expect(hub.db.queuePluginLogEntry).not.toHaveBeenCalled()
        })

        it('stops export if events fetch fails', async () => {
            jest.mocked(fetchEventsForInterval).mockRejectedValue(new Error('Fetch failed'))
            await storage().set(EXPORT_RUNNING_KEY, {
                id: 1,
                parallelism: 3,
                dateFrom: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
                dateTo: '2021-11-01T05:00:00.000Z' as ISOTimestamp,
            })

            await exportHistoricalEvents(defaultPayload)

            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'Failed fetching events. Stopping export - please try again later.'
                    ),
                })
            )
            expect(await storage().get(EXPORT_RUNNING_KEY, null)).toEqual(null)
        })

        it('schedules a retry if exportEvents raises a RetryError', async () => {
            createVM()

            jest.mocked(fetchEventsForInterval).mockResolvedValue([1, 2, 3])
            jest.mocked(vm.methods.exportEvents).mockRejectedValue(new RetryError('Retry error'))

            await exportHistoricalEvents(defaultPayload)

            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'Failed processing events 0-3 from 2021-11-01T00:00:00.000Z to 2021-11-01T01:00:00.000Z.'
                    ),
                })
            )
            expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith({
                ...defaultPayload,
                retriesPerformedSoFar: 1,
            })
            expect(runIn).toHaveBeenCalledWith(3, 'seconds')
        })

        it('schedules a retry with exponential backoff', async () => {
            createVM()

            jest.mocked(fetchEventsForInterval).mockResolvedValue([1, 2, 3])
            jest.mocked(vm.methods.exportEvents).mockRejectedValue(new RetryError('Retry error'))

            await exportHistoricalEvents({ ...defaultPayload, retriesPerformedSoFar: 5 })

            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'Failed processing events 0-3 from 2021-11-01T00:00:00.000Z to 2021-11-01T01:00:00.000Z.'
                    ),
                })
            )
            expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith({
                ...defaultPayload,
                retriesPerformedSoFar: 6,
            })
            expect(runIn).toHaveBeenCalledWith(96, 'seconds')
        })

        it('stops processing date if an unknown error was raised in exportEvents', async () => {
            createVM()

            jest.mocked(fetchEventsForInterval).mockResolvedValue([1, 2, 3])
            jest.mocked(vm.methods.exportEvents).mockRejectedValue(new Error('Unknown error'))

            await exportHistoricalEvents(defaultPayload)

            expect(vm.meta.jobs.exportHistoricalEvents).not.toHaveBeenCalled()
            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'exportEvents returned unknown error, stopping export. error=Error: Unknown error'
                    ),
                })
            )

            expect(await storage().get(EXPORT_RUNNING_KEY, null)).toEqual(null)
        })

        it('stops processing after 15 retries', async () => {
            await exportHistoricalEvents({ ...defaultPayload, retriesPerformedSoFar: 15 })

            expect(fetchEventsForInterval).not.toHaveBeenCalled()
            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'Exporting events from 2021-11-01T00:00:00.000Z to 2021-11-01T05:00:00.000Z failed after 15 retries. Stopping export.'
                    ),
                })
            )

            expect(await storage().get(EXPORT_RUNNING_KEY, null)).toEqual(null)
        })

        it('does nothing if no export is running', async () => {
            await storage().del(EXPORT_RUNNING_KEY)

            await exportHistoricalEvents(defaultPayload)

            expect(fetchEventsForInterval).not.toHaveBeenCalled()
            expect(hub.db.queuePluginLogEntry).not.toHaveBeenCalled()
        })

        it('does nothing if a different export is running', async () => {
            await exportHistoricalEvents({ ...defaultPayload, exportId: 779 })

            expect(fetchEventsForInterval).not.toHaveBeenCalled()
            expect(hub.db.queuePluginLogEntry).not.toHaveBeenCalled()
        })

        describe('calling next time window', () => {
            it('calls next time range if this range was empty', async () => {
                jest.mocked(fetchEventsForInterval).mockResolvedValue([])

                await exportHistoricalEvents(defaultPayload)

                expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith({
                    ...defaultPayload,
                    timestampCursor: defaultPayload.timestampCursor + defaultPayload.fetchTimeInterval * 1.2,
                    offset: 0,
                    fetchTimeInterval: defaultPayload.fetchTimeInterval * 1.2,
                })
            })

            it('calls next time range if this range had some events', async () => {
                jest.mocked(fetchEventsForInterval).mockResolvedValue(new Array(400))

                await exportHistoricalEvents(defaultPayload)

                expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith({
                    ...defaultPayload,
                    timestampCursor: defaultPayload.timestampCursor + defaultPayload.fetchTimeInterval,
                    offset: 0,
                    fetchTimeInterval: defaultPayload.fetchTimeInterval,
                })
            })

            it('increases offset if this range had full page of events', async () => {
                jest.mocked(fetchEventsForInterval).mockResolvedValue(new Array(500))

                await exportHistoricalEvents(defaultPayload)

                expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith({
                    ...defaultPayload,
                    timestampCursor: defaultPayload.timestampCursor,
                    offset: 500,
                })
            })

            it('resets `retriesPerformedSoFar` and `offset` when page increases', async () => {
                jest.mocked(fetchEventsForInterval).mockResolvedValue(new Array(300))

                await exportHistoricalEvents({
                    ...defaultPayload,
                    offset: 1000,
                    retriesPerformedSoFar: 10,
                })

                expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith({
                    ...defaultPayload,
                    timestampCursor: defaultPayload.timestampCursor + defaultPayload.fetchTimeInterval,
                    offset: 0,
                    retriesPerformedSoFar: 0,
                })
            })

            it('does not cross endTime when bumping time window', async () => {
                jest.mocked(fetchEventsForInterval).mockResolvedValue(new Array(300))

                await exportHistoricalEvents({
                    ...defaultPayload,
                    timestampCursor: defaultPayload.endTime - 100,
                })

                expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith({
                    ...defaultPayload,
                    timestampCursor: defaultPayload.endTime,
                })
            })
        })
    })

    describe('coordinateHistoricExport()', () => {
        const coordinateHistoricExport = getTestMethod('coordinateHistoricExport')

        beforeEach(async () => {
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
                    toResume: [],
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
                    toResume: [],
                })

                expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith({
                    endTime: 1635742800000,
                    exportId: 1,
                    fetchTimeInterval: 600000,
                    offset: 0,
                    retriesPerformedSoFar: 0,
                    startTime: 1635724800000,
                    timestampCursor: 1635724800000,
                    statusKey: 'EXPORT_DATE_STATUS_2021-11-01T00:00:00.000Z',
                })

                expect(await storage().get('EXPORT_DATE_STATUS_2021-11-01T00:00:00.000Z', null)).toEqual(
                    expect.objectContaining({
                        done: false,
                        progress: 0,
                        statusTime: Date.now(),
                    })
                )
                expect(await storage().get('EXPORT_COORDINATION', null)).toEqual({
                    done: ['2021-10-29T00:00:00.000Z', '2021-10-30T00:00:00.000Z', '2021-10-31T00:00:00.000Z'],
                    running: ['2021-11-01T00:00:00.000Z'],
                    progress: 0.7553,
                })
            })

            it('resumes tasks and updates coordination if needed', async () => {
                const toResumePayload = {
                    done: false,
                    progress: 0.5,
                    statusTime: 5_000_000_000,
                    endTime: 1635742800000,
                    exportId: 1,
                    fetchTimeInterval: 600000,
                    offset: 0,
                    retriesPerformedSoFar: 0,
                    startTime: 1635724800000,
                    timestampCursor: 1635724800000,
                    statusKey: 'EXPORT_DATE_STATUS_2021-11-01T00:00:00.000Z',
                }

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
                    toStartRunning: [],
                    toResume: [toResumePayload],
                })

                expect(vm.meta.jobs.exportHistoricalEvents).toHaveBeenCalledWith(toResumePayload)
                expect(await storage().get('EXPORT_DATE_STATUS_2021-11-01T00:00:00.000Z', null)).toEqual(
                    expect.objectContaining({
                        done: false,
                        progress: 0.5,
                        statusTime: Date.now(),
                    })
                )
            })

            it('handles export being completed', async () => {
                await coordinateHistoricExport({
                    hasChanges: false,
                    exportIsDone: true,
                    progress: 1,
                    done: [],
                    running: [],
                    toStartRunning: [],
                    toResume: [],
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
                toResume: [],
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
                toResume: [],
                progress: 0,
                exportIsDone: false,
            })
        })

        it('marks running tasks as done and counts progress', async () => {
            await storage().set('EXPORT_DATE_STATUS_2021-10-29T00:00:00.000Z', {
                done: false,
                progress: 0.5,
                statusTime: Date.now() - 60_000,
            })
            await storage().set('EXPORT_DATE_STATUS_2021-10-30T00:00:00.000Z', {
                done: true,
                progress: 1,
                statusTime: Date.now() - 60_000,
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
                toResume: [],
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
                toResume: [],
                progress: 1,
                exportIsDone: true,
            })
        })

        it('resumes running task after a long enough of a delay', async () => {
            const dateStatus = {
                done: false,
                progress: 0.5,
                statusTime: Date.now() - 20 * 60 * 1000,
                retriesPerformedSoFar: 0,
            }
            await storage().set('EXPORT_DATE_STATUS_2021-10-29T00:00:00.000Z', dateStatus)

            const result = await calculateCoordination(params, [], [
                '2021-10-29T00:00:00.000Z',
                '2021-10-30T00:00:00.000Z',
                '2021-10-31T00:00:00.000Z',
            ] as ISOTimestamp[])

            expect(result).toEqual({
                hasChanges: true,
                done: [],
                running: ['2021-10-29T00:00:00.000Z', '2021-10-30T00:00:00.000Z', '2021-10-31T00:00:00.000Z'],
                toStartRunning: [],
                toResume: [dateStatus],
                progress: 0.125,
                exportIsDone: false,
            })
        })
    })

    describe('nextFetchTimeInterval()', () => {
        const nextFetchTimeInterval = getTestMethod('nextFetchTimeInterval')

        const defaultPayload: ExportHistoricalEventsJobPayload = {
            timestampCursor: 0,
            startTime: 0,
            endTime: 1000,
            offset: 0,
            retriesPerformedSoFar: 0,
            exportId: 0,
            fetchTimeInterval: ONE_HOUR,
            statusKey: 'abc',
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

    describe('stopExport()', () => {
        const stopExport = getTestMethod('stopExport')

        it('unsets EXPORT_RUNNING_KEY', async () => {
            await storage().set(EXPORT_RUNNING_KEY, {
                id: 1,
                parallelism: 3,
                dateFrom: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
                dateTo: '2021-11-01T05:00:00.000Z' as ISOTimestamp,
            })

            await stopExport('')

            expect(await storage().get(EXPORT_RUNNING_KEY, null)).toEqual(null)
        })
    })

    describe('shouldResume()', () => {
        const shouldResume = getTestMethod('shouldResume')

        it('resumes task when a bit over 10 minutes have passed', () => {
            const status = {
                statusTime: 10_000_000_000,
                retriesPerformedSoFar: 0,
            } as any

            expect(shouldResume(status, 10_000_000_000)).toEqual(false)
            expect(shouldResume(status, 9_000_000_000)).toEqual(false)
            expect(shouldResume(status, 10_000_060_000)).toEqual(false)
            expect(shouldResume(status, 10_000_590_000)).toEqual(false)
            expect(shouldResume(status, 10_000_660_000)).toEqual(true)
            expect(shouldResume(status, 10_001_000_000)).toEqual(true)
        })

        it('accounts for retries exponential backoff', () => {
            const status = {
                statusTime: 10_000_000_000,
                retriesPerformedSoFar: 10,
            } as any

            expect(shouldResume(status, 10_000_660_000)).toEqual(false)
            // Roughly 2**11*3 seconds are waited between retry 10 and 11
            expect(shouldResume(status, 10_006_000_000)).toEqual(false)
            expect(shouldResume(status, 10_006_200_000)).toEqual(false)
        })
    })
})
