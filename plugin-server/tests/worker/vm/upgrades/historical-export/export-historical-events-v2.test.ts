import { PluginMeta, RetryError } from '@posthog/plugin-scaffold'

import {
    Hub,
    ISOTimestamp,
    PluginConfig,
    PluginConfigVMInternalResponse,
    PluginTaskType,
} from '../../../../../src/types'
import { createPluginActivityLog } from '../../../../../src/utils/db/activity-log'
import { createHub } from '../../../../../src/utils/db/hub'
import { createStorage } from '../../../../../src/worker/vm/extensions/storage'
import { createUtils } from '../../../../../src/worker/vm/extensions/utilities'
import {
    addHistoricalEventsExportCapabilityV2,
    EVENTS_PER_RUN_SMALL,
    EXPORT_COORDINATION_KEY,
    EXPORT_PARAMETERS_KEY,
    ExportHistoricalEventsJobPayload,
    ExportHistoricalEventsUpgradeV2,
    INTERFACE_JOB_NAME,
    JOB_SPEC,
    TestFunctions,
} from '../../../../../src/worker/vm/upgrades/historical-export/export-historical-events-v2'
import { fetchEventsForInterval } from '../../../../../src/worker/vm/upgrades/utils/fetchEventsForInterval'
import { plugin60, pluginConfig39 } from '../../../../helpers/plugins'
import { resetTestDatabase } from '../../../../helpers/sql'

jest.mock('../../../../../src/utils/status')
jest.mock('../../../../../src/worker/vm/upgrades/utils/fetchEventsForInterval')
jest.mock('../../../../../src/utils/db/activity-log')

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
        jest.spyOn(hub.appMetrics, 'queueMetric')
        jest.spyOn(hub.appMetrics, 'queueError')

        jest.spyOn(Date, 'now').mockReturnValue(1_000_000_000)
    })

    afterAll(async () => {
        await hub.promiseManager.awaitPromisesIfNeeded()
        await closeHub()
    })

    function storage() {
        return createStorage(hub, pluginConfig39)
    }

    function createVM(pluginConfig: PluginConfig = pluginConfig39, schedule = {}) {
        runIn = jest.fn()
        runNow = jest.fn()

        const mockVM = {
            methods: {
                exportEvents: jest.fn(),
            },
            tasks: {
                schedule,
                job: {},
            },
            meta: {
                storage: storage(),
                utils: createUtils(hub, pluginConfig.id),
                jobs: {
                    exportHistoricalEventsV2: jest.fn().mockReturnValue({ runNow, runIn }),
                },
                global: {},
            },
        } as unknown as PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgradeV2>>

        addHistoricalEventsExportCapabilityV2(hub, pluginConfig, mockVM)

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
            await resetTestDatabase()
            await storage().set(EXPORT_PARAMETERS_KEY, {
                id: 1,
                parallelism: 3,
                dateFrom: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
                dateTo: '2021-11-01T05:00:00.000Z' as ISOTimestamp,
            })
        })

        afterEach(() => {
            jest.clearAllTimers()
            jest.useRealTimers()
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
                        'Finished exporting chunk from 2021-11-01T00:00:00.000Z to 2021-11-01T05:00:00.000Z'
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
            createVM()

            jest.useFakeTimers({
                // These are required otherwise queries and other things were breaking.
                doNotFake: ['setImmediate', 'clearImmediate', 'clearInterval', 'nextTick', 'Date'],
            })

            jest.spyOn(vm.meta.storage, 'set')
            jest.spyOn(vm.meta.storage, 'updateStatusTime')
            jest.spyOn(global, 'clearInterval')

            const defaultProgress =
                (defaultPayload.timestampCursor - defaultPayload.startTime) /
                (defaultPayload.endTime - defaultPayload.startTime)

            jest.mocked(vm.methods.exportEvents).mockImplementationOnce(async () => {
                let advanced = 0
                while (advanced < 3) {
                    // This 1 check accounts for the first status update that happens once at the beginning of
                    // exportHistoricalEvents.
                    expect(vm.meta.storage.set).toHaveBeenCalledTimes(1)
                    expect(vm.meta.storage.updateStatusTime).toHaveBeenCalledTimes(advanced)

                    expect(await storage().get('statusKey', null)).toEqual({
                        ...defaultPayload,
                        timestampCursor: defaultPayload.startTime,
                        done: false,
                        progress: defaultProgress,
                        statusTime: Date.now(),
                    })

                    advanced = advanced + 1
                    jest.advanceTimersByTime(60 * 1000)
                }
                return
            })
            jest.mocked(fetchEventsForInterval).mockResolvedValue([1, 2, 3])

            await exportHistoricalEvents(defaultPayload)

            expect(clearInterval).toHaveBeenCalledTimes(1)
            expect(vm.methods.exportEvents).toHaveBeenCalledWith([1, 2, 3])
            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'Successfully processed events 0-3 from 2021-11-01T00:00:00.000Z to 2021-11-01T01:00:00.000Z.'
                    ),
                })
            )
            expect(jest.mocked(hub.appMetrics.queueMetric).mock.calls).toMatchSnapshot()
        })

        it('does not call exportEvents or log if no events in time range', async () => {
            jest.mocked(fetchEventsForInterval).mockResolvedValue([])
            jest.spyOn(global, 'clearInterval')

            await exportHistoricalEvents(defaultPayload)

            expect(clearInterval).toHaveBeenCalledTimes(1)
            expect(vm.methods.exportEvents).not.toHaveBeenCalled()
            expect(hub.db.queuePluginLogEntry).not.toHaveBeenCalled()
        })

        it('stops export if events fetch fails', async () => {
            jest.mocked(fetchEventsForInterval).mockRejectedValue(new Error('Fetch failed'))
            await storage().set(EXPORT_PARAMETERS_KEY, {
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
            expect(await storage().get(EXPORT_PARAMETERS_KEY, null)).toEqual(null)
        })

        it('schedules a retry if exportEvents raises a RetryError', async () => {
            createVM()

            jest.spyOn(global, 'clearInterval')
            jest.mocked(fetchEventsForInterval).mockResolvedValue([1, 2, 3])
            jest.mocked(vm.methods.exportEvents).mockRejectedValue(new RetryError('Retry error'))

            await exportHistoricalEvents(defaultPayload)

            expect(clearInterval).toHaveBeenCalledTimes(1)
            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'Failed processing events 0-3 from 2021-11-01T00:00:00.000Z to 2021-11-01T01:00:00.000Z.'
                    ),
                })
            )
            expect(vm.meta.jobs.exportHistoricalEventsV2).toHaveBeenCalledWith({
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
            expect(vm.meta.jobs.exportHistoricalEventsV2).toHaveBeenCalledWith({
                ...defaultPayload,
                retriesPerformedSoFar: 6,
            })
            expect(runIn).toHaveBeenCalledWith(96, 'seconds')
        })

        it('stops processing date if an unknown error was raised in exportEvents', async () => {
            createVM()

            jest.spyOn(global, 'clearInterval')
            jest.mocked(fetchEventsForInterval).mockResolvedValue([1, 2, 3])
            jest.mocked(vm.methods.exportEvents).mockRejectedValue(new Error('Unknown error'))

            await exportHistoricalEvents(defaultPayload)

            expect(clearInterval).toHaveBeenCalledTimes(1)
            expect(vm.meta.jobs.exportHistoricalEventsV2).not.toHaveBeenCalled()
            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        'exportEvents returned unknown error, stopping export. error=Error: Unknown error'
                    ),
                })
            )
            expect(jest.mocked(hub.appMetrics.queueError).mock.calls).toMatchSnapshot()

            expect(await storage().get(EXPORT_PARAMETERS_KEY, null)).toEqual(null)
        })

        it('stops processing after HISTORICAL_EXPORTS_MAX_RETRY_COUNT retries', async () => {
            createVM()

            jest.mocked(fetchEventsForInterval).mockResolvedValue([1, 2, 3])
            jest.mocked(vm.methods.exportEvents).mockRejectedValue(new RetryError('Retry error'))

            await exportHistoricalEvents({
                ...defaultPayload,
                retriesPerformedSoFar: hub.HISTORICAL_EXPORTS_MAX_RETRY_COUNT - 1,
            })

            expect(vm.meta.jobs.exportHistoricalEventsV2).not.toHaveBeenCalled()
            expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                expect.objectContaining({
                    message: expect.stringContaining(
                        `Exporting chunk 2021-11-01T00:00:00.000Z to 2021-11-01T05:00:00.000Z failed after ${hub.HISTORICAL_EXPORTS_MAX_RETRY_COUNT} retries. Stopping export.`
                    ),
                })
            )
            expect(jest.mocked(hub.appMetrics.queueError).mock.calls).toMatchSnapshot()

            expect(await storage().get(EXPORT_PARAMETERS_KEY, null)).toEqual(null)
        })

        it('does nothing if no export is running', async () => {
            await storage().del(EXPORT_PARAMETERS_KEY)

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

                expect(vm.meta.jobs.exportHistoricalEventsV2).toHaveBeenCalledWith({
                    ...defaultPayload,
                    timestampCursor: defaultPayload.timestampCursor + defaultPayload.fetchTimeInterval,
                    offset: 0,
                    fetchTimeInterval:
                        defaultPayload.fetchTimeInterval * hub.HISTORICAL_EXPORTS_FETCH_WINDOW_MULTIPLIER,
                })
            })

            it('calls next time range if this range had some events', async () => {
                jest.mocked(fetchEventsForInterval).mockResolvedValue(new Array(400))

                await exportHistoricalEvents(defaultPayload)

                expect(vm.meta.jobs.exportHistoricalEventsV2).toHaveBeenCalledWith({
                    ...defaultPayload,
                    timestampCursor: defaultPayload.timestampCursor + defaultPayload.fetchTimeInterval,
                    offset: 0,
                    fetchTimeInterval: defaultPayload.fetchTimeInterval,
                })
            })

            it('increases offset if this range had full page of events', async () => {
                jest.mocked(fetchEventsForInterval).mockResolvedValue(new Array(500))

                await exportHistoricalEvents(defaultPayload)

                expect(vm.meta.jobs.exportHistoricalEventsV2).toHaveBeenCalledWith({
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

                expect(vm.meta.jobs.exportHistoricalEventsV2).toHaveBeenCalledWith({
                    ...defaultPayload,
                    timestampCursor: defaultPayload.timestampCursor + defaultPayload.fetchTimeInterval,
                    offset: 0,
                    retriesPerformedSoFar: 0,
                })
            })
        })
    })

    describe('coordinateHistoricalExport()', () => {
        const coordinateHistoricalExport = getTestMethod('coordinateHistoricalExport')

        beforeEach(async () => {
            await resetTestDatabase()
        })

        it('does nothing if export isnt running / is done', async () => {
            await coordinateHistoricalExport()

            expect(await storage().get(EXPORT_COORDINATION_KEY, null)).toEqual(null)
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
                await storage().set(EXPORT_PARAMETERS_KEY, params)
            })

            it('logs progress of the export and does not start excessive jobs', async () => {
                await coordinateHistoricalExport({
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
                        message: expect.stringContaining('Export progress: ■■■■■■■■■■■■■■■□□□□□ (75.5%)'),
                    })
                )

                expect(vm.meta.jobs.exportHistoricalEventsV2).not.toHaveBeenCalled()
                expect(await storage().get(EXPORT_PARAMETERS_KEY, null)).toEqual(params)
            })

            it('starts up new jobs and updates coordination data if needed', async () => {
                await coordinateHistoricalExport({
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

                expect(vm.meta.jobs.exportHistoricalEventsV2).toHaveBeenCalledWith({
                    endTime: 1635742800000,
                    exportId: 1,
                    fetchTimeInterval: hub.HISTORICAL_EXPORTS_INITIAL_FETCH_TIME_WINDOW,
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
                expect(await storage().get(EXPORT_COORDINATION_KEY, null)).toEqual({
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
                    fetchTimeInterval: hub.HISTORICAL_EXPORTS_INITIAL_FETCH_TIME_WINDOW,
                    offset: 0,
                    retriesPerformedSoFar: 0,
                    startTime: 1635724800000,
                    timestampCursor: 1635724800000,
                    statusKey: 'EXPORT_DATE_STATUS_2021-11-01T00:00:00.000Z',
                }

                await coordinateHistoricalExport({
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

                expect(vm.meta.jobs.exportHistoricalEventsV2).toHaveBeenCalledWith(toResumePayload)
                expect(await storage().get('EXPORT_DATE_STATUS_2021-11-01T00:00:00.000Z', null)).toEqual(
                    expect.objectContaining({
                        done: false,
                        progress: 0.5,
                        statusTime: Date.now(),
                    })
                )
            })

            it('handles export being completed', async () => {
                await coordinateHistoricalExport({
                    hasChanges: false,
                    exportIsDone: true,
                    progress: 1,
                    done: [],
                    running: [],
                    toStartRunning: [],
                    toResume: [],
                })

                expect(hub.db.queuePluginLogEntry).toHaveBeenCalledWith(
                    expect.objectContaining({
                        message: expect.stringContaining('Export has finished!'),
                    })
                )
                expect(await storage().get(EXPORT_PARAMETERS_KEY, null)).toEqual(null)
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
                statusTime: Date.now() - 70 * 60 * 1000,
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

        it('does not resume tasks that are done', async () => {
            const dateStatus = {
                done: true,
                progress: 1,
                statusTime: Date.now() - 70 * 60 * 1000,
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
                done: ['2021-10-29T00:00:00.000Z'],
                running: ['2021-10-30T00:00:00.000Z', '2021-10-31T00:00:00.000Z', '2021-11-01T00:00:00.000Z'],
                toStartRunning: [['2021-11-01T00:00:00.000Z', '2021-11-01T05:00:00.000Z']],
                toResume: [],
                progress: 0.25,
                exportIsDone: false,
            })
        })
    })

    describe('nextCursor()', () => {
        const nextCursor = getTestMethod('nextCursor')

        const defaultPayload: ExportHistoricalEventsJobPayload = {
            timestampCursor: 0,
            startTime: 0,
            endTime: 1_000_000_000,
            offset: 0,
            retriesPerformedSoFar: 0,
            exportId: 0,
            fetchTimeInterval: ONE_HOUR,
            statusKey: 'abc',
        }

        it('increases only offset if more in current time range', () => {
            expect(nextCursor(defaultPayload, EVENTS_PER_RUN_SMALL)).toEqual({
                timestampCursor: defaultPayload.timestampCursor,
                fetchTimeInterval: ONE_HOUR,
                offset: EVENTS_PER_RUN_SMALL,
            })
        })
        it('increases only offset if more in current time range on a late page', () => {
            expect(nextCursor({ ...defaultPayload, offset: 5 * EVENTS_PER_RUN_SMALL }, EVENTS_PER_RUN_SMALL)).toEqual({
                timestampCursor: defaultPayload.timestampCursor,
                fetchTimeInterval: ONE_HOUR,
                offset: 6 * EVENTS_PER_RUN_SMALL,
            })
        })

        it('returns existing fetchTimeInterval if time range mostly full', () => {
            expect(nextCursor(defaultPayload, EVENTS_PER_RUN_SMALL * 0.9)).toEqual({
                timestampCursor: defaultPayload.timestampCursor + defaultPayload.fetchTimeInterval,
                fetchTimeInterval: ONE_HOUR,
                offset: 0,
            })
        })

        it('increases fetchTimeInterval if time range mostly empty', () => {
            expect(nextCursor(defaultPayload, EVENTS_PER_RUN_SMALL * 0.1)).toEqual({
                timestampCursor: defaultPayload.timestampCursor + defaultPayload.fetchTimeInterval,
                fetchTimeInterval: ONE_HOUR * hub.HISTORICAL_EXPORTS_FETCH_WINDOW_MULTIPLIER,
                offset: 0,
            })
        })

        it('does not increase fetchTimeInterval beyond 12 hours', () => {
            const payload = {
                ...defaultPayload,
                fetchTimeInterval: 11.5 * 60 * 60 * 1000, // 11.5 hours
            }
            expect(nextCursor(payload, EVENTS_PER_RUN_SMALL * 0.1)).toEqual({
                timestampCursor: payload.timestampCursor + payload.fetchTimeInterval,
                fetchTimeInterval: 12 * 60 * 60 * 1000,
                offset: 0,
            })
        })

        it('decreases fetchTimeInterval if on a late page and no more to fetch', () => {
            expect(nextCursor({ ...defaultPayload, offset: 5 * EVENTS_PER_RUN_SMALL }, 10)).toEqual({
                timestampCursor: defaultPayload.timestampCursor + defaultPayload.fetchTimeInterval,
                fetchTimeInterval: ONE_HOUR / hub.HISTORICAL_EXPORTS_FETCH_WINDOW_MULTIPLIER,
                offset: 0,
            })
        })

        it('does not decrease fetchTimeInterval below 10 minutes', () => {
            const payload = {
                ...defaultPayload,
                offset: 5 * EVENTS_PER_RUN_SMALL,
                fetchTimeInterval: 10.5 * 60 * 1000, // 10.5 minutes
            }

            expect(nextCursor(payload, 10)).toEqual({
                timestampCursor: payload.timestampCursor + payload.fetchTimeInterval,
                fetchTimeInterval: 10 * 60 * 1000,
                offset: 0,
            })
        })

        it('reduces fetchTimeInterval if it would result going beyond endTime', () => {
            const payload = {
                ...defaultPayload,
                endTime: 6_500_000,
                timestampCursor: 5_000_000,
                fetchTimeInterval: 1_000_000,
                offset: 0,
            }

            expect(nextCursor(payload, 10)).toEqual({
                timestampCursor: 6_000_000,
                fetchTimeInterval: 500_000,
                offset: 0,
            })
        })

        it('make sure to use a larger batch size if the plugin recommends it', () => {
            // NOTE: this doesn't actually check that this value is used in the
            // requests to ClickHouse, but :fingercrossed: it's good enough.
            createVM()

            // When no settings are returned, the default small batch size is used
            let eventsPerRun = addHistoricalEventsExportCapabilityV2(
                hub,
                { plugin: { name: 'S3 Export Plugin' } } as any,
                vm
            ).eventsPerRun
            expect(eventsPerRun).toEqual(500)

            // Set the handlesLargeBatches flag to true and expect a big batch size
            vm.methods.getSettings = jest.fn().mockReturnValue({
                handlesLargeBatches: true,
            })
            eventsPerRun = addHistoricalEventsExportCapabilityV2(
                hub,
                { plugin: { name: 'S3 Export Plugin' } } as any,
                vm
            ).eventsPerRun
            expect(eventsPerRun).toEqual(10000)

            // Keep the default of 500 if the flag is false
            vm.methods.getSettings = jest.fn().mockReturnValue({
                handlesLargeBatches: false,
            })
            eventsPerRun = addHistoricalEventsExportCapabilityV2(
                hub,
                { plugin: { name: 'foo' } } as any,
                vm
            ).eventsPerRun
            expect(eventsPerRun).toEqual(500)
        })
    })

    describe('getTimestampBoundaries()', () => {
        const getTimestampBoundaries = getTestMethod('getTimestampBoundaries')

        it('returns timestamp boundaries passed into interface job, increasing the end date by a day', () => {
            expect(
                getTimestampBoundaries({
                    dateRange: ['2021-10-29', '2021-11-30'],
                })
            ).toEqual(['2021-10-29T00:00:00.000Z', '2021-12-01T00:00:00.000Z'])
        })

        it('raises an error for invalid timestamp formats', () => {
            expect(() =>
                getTimestampBoundaries({
                    dateRange: ['foo', 'bar'],
                })
            ).toThrow("'dateRange' should be two dates in ISO string format.")
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

        const params = {
            id: 1,
            parallelism: 3,
            dateFrom: '2021-10-29T00:00:00.000Z' as ISOTimestamp,
            dateTo: '2021-11-01T05:00:00.000Z' as ISOTimestamp,
        }

        it('unsets EXPORT_PARAMETERS_KEY', async () => {
            await storage().set(EXPORT_PARAMETERS_KEY, params)

            await stopExport(params, '', 'success')

            expect(await storage().get(EXPORT_PARAMETERS_KEY, null)).toEqual(null)
        })

        it('captures activity for export success', async () => {
            await stopExport(params, '', 'success')

            expect(createPluginActivityLog).toHaveBeenCalledWith(
                hub,
                pluginConfig39.team_id,
                pluginConfig39.id,
                'export_success',
                {
                    trigger: {
                        job_id: '1',
                        job_type: INTERFACE_JOB_NAME,
                        payload: params,
                    },
                }
            )
        })

        it('captures activity for export failure', async () => {
            await stopExport(params, 'Some error message', 'fail')

            expect(createPluginActivityLog).toHaveBeenCalledWith(
                hub,
                pluginConfig39.team_id,
                pluginConfig39.id,
                'export_fail',
                {
                    trigger: {
                        job_id: '1',
                        job_type: INTERFACE_JOB_NAME,
                        payload: {
                            ...params,
                            failure_reason: 'Some error message',
                        },
                    },
                }
            )
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
            expect(shouldResume(status, 10_000_600_000)).toEqual(false)
            expect(shouldResume(status, 10_003_660_000)).toEqual(true)
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

    describe('updating public jobs', () => {
        beforeEach(() => {
            jest.spyOn(hub.db, 'addOrUpdatePublicJob')
        })

        it('updates when public job has not been yet registered', () => {
            const pluginConfig: PluginConfig = {
                ...pluginConfig39,
                plugin: {
                    ...plugin60,
                    public_jobs: {},
                },
            }
            createVM(pluginConfig)

            expect(hub.db.addOrUpdatePublicJob).toHaveBeenCalledWith(
                pluginConfig39.plugin_id,
                INTERFACE_JOB_NAME,
                JOB_SPEC
            )
        })

        it('updates when public job definition has changed', () => {
            const pluginConfig: PluginConfig = {
                ...pluginConfig39,
                plugin: {
                    ...plugin60,
                    public_jobs: { [INTERFACE_JOB_NAME]: { payload: {} } },
                },
            }
            createVM(pluginConfig)

            expect(hub.db.addOrUpdatePublicJob).toHaveBeenCalledWith(
                pluginConfig39.plugin_id,
                INTERFACE_JOB_NAME,
                JOB_SPEC
            )
        })

        it('does not update if public job has already been registered', () => {
            const pluginConfig: PluginConfig = {
                ...pluginConfig39,
                plugin: {
                    ...plugin60,
                    public_jobs: { [INTERFACE_JOB_NAME]: JOB_SPEC },
                },
            }
            createVM(pluginConfig)

            expect(hub.db.addOrUpdatePublicJob).not.toHaveBeenCalled()
        })
    })

    describe('tasks.schedule.runEveryMinute()', () => {
        it('sets __ignoreForAppMetrics if runEveryMinute was not previously defined', async () => {
            createVM()

            expect(vm.tasks.schedule.runEveryMinute).toEqual({
                name: 'runEveryMinute',
                type: PluginTaskType.Schedule,
                exec: expect.any(Function),
                __ignoreForAppMetrics: true,
            })

            await vm.tasks.schedule.runEveryMinute.exec()
        })

        it('calls original method and does not set __ignoreForAppMetrics if runEveryMinute was previously defined in plugin', async () => {
            const pluginRunEveryMinute = jest.fn()

            createVM(pluginConfig39, {
                runEveryMinute: {
                    name: 'runEveryMinute',
                    type: PluginTaskType.Schedule,
                    exec: pluginRunEveryMinute,
                },
            })

            expect(vm.tasks.schedule.runEveryMinute).toEqual({
                name: 'runEveryMinute',
                type: PluginTaskType.Schedule,
                exec: expect.any(Function),
                __ignoreForAppMetrics: false,
            })

            await vm.tasks.schedule.runEveryMinute.exec()

            expect(pluginRunEveryMinute).toHaveBeenCalled()
        })

        it('calls original method and sets __ignoreForAppMetrics if runEveryMinute was previously also wrapped', async () => {
            const pluginRunEveryMinute = jest.fn()

            createVM(pluginConfig39, {
                runEveryMinute: {
                    name: 'runEveryMinute',
                    type: PluginTaskType.Schedule,
                    exec: pluginRunEveryMinute,
                    __ignoreForAppMetrics: true,
                },
            })

            expect(vm.tasks.schedule.runEveryMinute).toEqual({
                name: 'runEveryMinute',
                type: PluginTaskType.Schedule,
                exec: expect.any(Function),
                __ignoreForAppMetrics: true,
            })

            await vm.tasks.schedule.runEveryMinute.exec()

            expect(pluginRunEveryMinute).toHaveBeenCalled()
        })
    })
})
