/*
Historical exports (v2) work the following way:

- User triggers a `Export historical events V2` job from the UI.
  This saves the time range as the running export with parallelism options.
- `runEveryMinute` acts as a coordinator: It takes the time range job runs on, splits it into chunks,
  ensures that enough pieces are running, reports progress and finalizes the export.
    - If a certain running chunk hasn't reported progress in a while, it is also restarted.
- `exportHistoricalEvents` job is responsible for exporting data between particular start and end points (chunk)
    - It tracks its progress under `statusKey`
    - It dynamically resizes the time window we fetch data to minimize jobs that need to be scheduled and clickhouse queries
    - It calls plugins `exportEvents` with each batch of events it finds
    - It handles retries by retrying RetryErrors up to 15 times

Error handling:
- Failing to fetch events from clickhouse stops the export outright
- For every batch of events fetched, `exportEvents` RetryError is retried up to 15 times
- Unknown errors raised by `exportEvents` cause export to fail
- We periodically check whether a running chunk has made progress. If not, the chunk is restarted

Note:
- parallelism is only settable by superusers to avoid abuse.
- Double-processing might be possible if a task is queued in graphile for a long time
*/

import { Plugin, PluginEvent, PluginMeta, RetryError } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'

import {
    Hub,
    ISOTimestamp,
    JobSpec,
    PluginConfig,
    PluginConfigVMInternalResponse,
    PluginLogEntry,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginTask,
    PluginTaskType,
} from '../../../../types'
import { processError } from '../../../../utils/db/error'
import { isTestEnv } from '../../../../utils/env-utils'
import { fetchEventsForInterval } from '../utils/fetchEventsForInterval'
import { TimestampBoundaries } from '../utils/utils'

const TEN_MINUTES = 1000 * 60 * 10
const TWELVE_HOURS = 1000 * 60 * 60 * 12
const EVENTS_TIME_INTERVAL = TEN_MINUTES
export const EVENTS_PER_RUN = 500

export const EXPORT_PARAMETERS_KEY = 'EXPORT_PARAMETERS'
export const EXPORT_COORDINATION_KEY = 'EXPORT_COORDINATION'

const INTERFACE_JOB_NAME = 'Export historical events V2'

const JOB_SPEC: JobSpec = {
    payload: {
        dateFrom: {
            title: 'Export start date',
            type: 'date',
            required: true,
        },
        dateTo: {
            title: 'Export end date (not inclusive)',
            type: 'date',
            required: true,
        },
        parallelism: {
            title: 'Parallelism',
            type: 'number',
            required: true,
            default: 1,
            staff_only: true,
        },
    },
}

export interface TestFunctions {
    exportHistoricalEvents: (payload: ExportHistoricalEventsJobPayload) => Promise<void>
    getTimestampBoundaries: (payload: ExportHistoricalEventsUIPayload) => TimestampBoundaries
    nextCursor: (payload: ExportHistoricalEventsJobPayload, eventCount: number) => OffsetParams
    coordinateHistoricalExport: (update?: CoordinationUpdate) => Promise<void>
    calculateCoordination: (
        params: ExportParams,
        done: Array<ISOTimestamp>,
        running: Array<ISOTimestamp>
    ) => Promise<CoordinationUpdate>
    getExportDateRange: (params: ExportParams) => Array<[ISOTimestamp, ISOTimestamp]>
    progressBar: (progress: number, length?: number) => string
    stopExport: (message: string) => Promise<void>
    shouldResume: (status: ExportChunkStatus, now: number) => void
}

export type ExportHistoricalEventsUpgradeV2 = Plugin<{
    global: {
        _testFunctions: TestFunctions
    }
}>

export interface ExportHistoricalEventsJobPayload {
    // Current cursor to what's being exported
    timestampCursor: number

    // The lower and upper bound of the timestamp interval to be processed
    startTime: number
    endTime: number

    // The offset *within* a given timestamp interval
    offset: number

    // how many retries a payload has had (max = 15)
    retriesPerformedSoFar: number

    // used for ensuring only one "export task" is running if the server restarts
    exportId: number

    // Time frame to fetch events for.
    fetchTimeInterval: number

    // Key to report export status to
    statusKey: string
}

type OffsetParams = Pick<ExportHistoricalEventsJobPayload, 'timestampCursor' | 'fetchTimeInterval' | 'offset'>

export interface ExportHistoricalEventsUIPayload {
    // Only set starting export from UI
    parallelism?: number
    dateFrom: string
    dateTo: string
}

export interface ExportParams {
    id: number
    parallelism: number
    dateFrom: ISOTimestamp
    dateTo: ISOTimestamp
}

interface CoordinationPayload {
    running?: Array<ISOTimestamp>
    done?: Array<ISOTimestamp>
    progress?: number
}

interface CoordinationUpdate {
    hasChanges: boolean
    done: Array<ISOTimestamp>
    running: Array<ISOTimestamp>
    toStartRunning: Array<[ISOTimestamp, ISOTimestamp]>
    toResume: Array<ExportChunkStatus>
    progress: number
    exportIsDone: boolean
}

export interface ExportChunkStatus extends ExportHistoricalEventsJobPayload {
    done: boolean
    progress: number
    // When was this status recorded
    statusTime: number
}

export function addHistoricalEventsExportCapabilityV2(
    hub: Hub,
    pluginConfig: PluginConfig,
    response: PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgradeV2>>
): void {
    const { methods, tasks, meta } = response

    const currentPublicJobs = pluginConfig.plugin?.public_jobs || {}

    if (!(INTERFACE_JOB_NAME in currentPublicJobs)) {
        hub.promiseManager.trackPromise(
            hub.db.addOrUpdatePublicJob(pluginConfig.plugin_id, INTERFACE_JOB_NAME, JOB_SPEC)
        )
    }

    const oldRunEveryMinute = tasks.schedule.runEveryMinute?.exec

    tasks.job[INTERFACE_JOB_NAME] = {
        name: INTERFACE_JOB_NAME,
        type: PluginTaskType.Job,
        exec: async (payload: ExportHistoricalEventsUIPayload) => {
            // only let one export run at a time
            const alreadyRunningExport = await getExportParameters()
            if (!!alreadyRunningExport) {
                createLog('Export already running, not starting another.', {
                    type: PluginLogEntryType.Warn,
                })
                return
            }

            // Clear old (conflicting) storage
            await meta.storage.del(EXPORT_COORDINATION_KEY)

            const id = Math.floor(Math.random() * 10000 + 1)
            const parallelism = Number(payload.parallelism ?? 1)
            const boundaries = getTimestampBoundaries(payload)

            await meta.storage.set(EXPORT_PARAMETERS_KEY, {
                id,
                parallelism,
                dateFrom: boundaries.min.toISOString(),
                dateTo: boundaries.max.toISOString(),
            } as ExportParams)

            createLog(
                `Starting export ${boundaries.min.toISOString()} - ${boundaries.max.toISOString()}. id=${id}, parallelism=${parallelism}`,
                {
                    type: PluginLogEntryType.Info,
                }
            )

            await coordinateHistoricalExport()
        },
    } as unknown as PluginTask // :KLUDGE: Work around typing limitations

    tasks.job['exportHistoricalEventsV2'] = {
        name: 'exportHistoricalEventsV2',
        type: PluginTaskType.Job,
        exec: (payload) => exportHistoricalEvents(payload as ExportHistoricalEventsJobPayload),
    }

    tasks.schedule.runEveryMinute = {
        name: 'runEveryMinute',
        type: PluginTaskType.Schedule,
        exec: async () => {
            await oldRunEveryMinute?.()
            await coordinateHistoricalExport()
        },
    }

    async function coordinateHistoricalExport(update?: CoordinationUpdate) {
        const params = await getExportParameters()

        if (!params) {
            // No export running!
            return
        }

        const { done, running } = (await meta.storage.get(EXPORT_COORDINATION_KEY, {})) as CoordinationPayload
        update = update || (await calculateCoordination(params, done || [], running || []))

        createLog(`Export progress: ${progressBar(update.progress)} (${Math.round(1000 * update.progress) / 10}%)`, {
            type: PluginLogEntryType.Info,
        })

        if (update.exportIsDone) {
            await stopExport('Export has finished! 💯', { type: PluginLogEntryType.Info })
            return
        }

        if (update.hasChanges) {
            await Promise.all(
                update.toStartRunning.map(async ([startDate, endDate]) => {
                    createLog(`Starting job to export ${startDate} to ${endDate}`, { type: PluginLogEntryType.Debug })

                    const payload: ExportHistoricalEventsJobPayload = {
                        timestampCursor: new Date(startDate).getTime(),
                        startTime: new Date(startDate).getTime(),
                        endTime: new Date(endDate).getTime(),
                        offset: 0,
                        retriesPerformedSoFar: 0,
                        exportId: params.id,
                        fetchTimeInterval: EVENTS_TIME_INTERVAL,
                        statusKey: `EXPORT_DATE_STATUS_${startDate}`,
                    }
                    await startChunk(payload, 0)
                })
            )

            await Promise.all(
                update.toResume.map(async (payload: ExportChunkStatus) => {
                    createLog(
                        `Export chunk from ${dateRange(
                            payload.startTime,
                            payload.endTime
                        )} seems inactive, restarting!`,
                        { type: PluginLogEntryType.Debug }
                    )
                    await startChunk(payload, payload.progress)
                })
            )

            await meta.storage.set(`EXPORT_COORDINATION`, {
                done: update.done,
                running: update.running,
                progress: update.progress,
            })
        }
    }

    async function calculateCoordination(
        params: ExportParams,
        done: Array<ISOTimestamp>,
        running: Array<ISOTimestamp>
    ): Promise<CoordinationUpdate> {
        const now = Date.now()
        const allDates = getExportDateRange(params)

        let hasChanges = false
        const doneDates = new Set(done)
        const runningDates = new Set(running)
        const progressPerDay = 1.0 / allDates.length

        let progress = progressPerDay * done.length
        const toResume: Array<ExportChunkStatus> = []

        for (const date of running || []) {
            const dateStatus = (await meta.storage.get(`EXPORT_DATE_STATUS_${date}`, null)) as ExportChunkStatus | null

            if (dateStatus?.done) {
                hasChanges = true
                doneDates.add(date)
                runningDates.delete(date)
                progress += progressPerDay
            } else {
                progress += progressPerDay * (dateStatus?.progress ?? 0)
            }

            if (dateStatus && shouldResume(dateStatus, now)) {
                hasChanges = true
                toResume.push(dateStatus)
            }
        }

        const toStartRunning: Array<[ISOTimestamp, ISOTimestamp]> = []

        if (runningDates.size < params.parallelism && doneDates.size + runningDates.size < allDates.length) {
            for (const [startDate, endDate] of allDates) {
                if (!doneDates.has(startDate) && !runningDates.has(startDate)) {
                    runningDates.add(startDate)
                    toStartRunning.push([startDate, endDate])
                    hasChanges = true

                    if (runningDates.size === params.parallelism) {
                        break
                    }
                }
            }
        }

        return {
            hasChanges,
            done: Array.from(doneDates.values()),
            running: Array.from(runningDates.values()),
            toStartRunning,
            toResume,
            progress,
            exportIsDone: doneDates.size === allDates.length,
        }
    }

    async function startChunk(payload: ExportHistoricalEventsJobPayload, progress: number): Promise<void> {
        // Save for detecting retries
        await meta.storage.set(payload.statusKey, {
            ...payload,
            done: false,
            progress,
            statusTime: Date.now(),
        } as ExportChunkStatus)

        // Start the job
        await meta.jobs.exportHistoricalEventsV2(payload).runNow()
    }

    async function exportHistoricalEvents(payload: ExportHistoricalEventsJobPayload): Promise<void> {
        const activeExportParameters = await getExportParameters()
        if (activeExportParameters?.id != payload.exportId) {
            // This export has finished or has been stopped
            return
        }

        if (payload.retriesPerformedSoFar >= 15) {
            const message = `Exporting chunk ${dateRange(
                payload.startTime,
                payload.endTime
            )} failed after 15 retries. Stopping export.`
            await stopExport(message, { type: PluginLogEntryType.Error })
            await processError(hub, pluginConfig, message)
            return
        }

        if (payload.timestampCursor >= payload.endTime) {
            createLog(`Finished exporting chunk from ${dateRange(payload.startTime, payload.endTime)}`, {
                type: PluginLogEntryType.Debug,
            })
            await meta.storage.set(payload.statusKey, {
                done: true,
                progress: 1,
                statusTime: Date.now(),
                ...payload,
            } as ExportChunkStatus)

            return
        }

        await meta.storage.set(payload.statusKey, {
            done: false,
            progress: (payload.timestampCursor - payload.startTime) / (payload.endTime - payload.startTime),
            statusTime: Date.now(),
            ...payload,
        } as ExportChunkStatus)

        let events: PluginEvent[] = []

        try {
            events = await fetchEventsForInterval(
                hub.db,
                pluginConfig.team_id,
                new Date(payload.timestampCursor),
                payload.offset,
                payload.fetchTimeInterval,
                EVENTS_PER_RUN
            )
        } catch (error) {
            Sentry.captureException(error)
            await processError(hub, pluginConfig, error)
            await stopExport('Failed fetching events. Stopping export - please try again later.', {
                type: PluginLogEntryType.Error,
            })
            return
        }

        if (events.length > 0) {
            try {
                await methods.exportEvents!(events)

                createLog(
                    `Successfully processed events ${payload.offset}-${payload.offset + events.length} from ${dateRange(
                        payload.timestampCursor,
                        payload.timestampCursor + payload.fetchTimeInterval
                    )}.`,
                    { type: PluginLogEntryType.Debug }
                )
            } catch (error) {
                await handleExportError(error, payload, events.length)
                return
            }
        }

        const { timestampCursor, fetchTimeInterval, offset } = nextCursor(payload, events.length)

        await meta.jobs
            .exportHistoricalEventsV2({
                ...payload,
                retriesPerformedSoFar: 0,
                timestampCursor,
                offset,
                fetchTimeInterval,
            } as ExportHistoricalEventsJobPayload)
            .runIn(1, 'seconds')
    }

    async function handleExportError(
        error: Error,
        payload: ExportHistoricalEventsJobPayload,
        eventCount: number
    ): Promise<void> {
        if (error instanceof RetryError) {
            const nextRetrySeconds = retryDelaySeconds(payload.retriesPerformedSoFar)

            createLog(
                `Failed processing events ${payload.offset}-${payload.offset + eventCount} from ${dateRange(
                    payload.timestampCursor,
                    payload.timestampCursor + payload.fetchTimeInterval
                )}. Retrying in ${nextRetrySeconds}s`,
                {
                    type: PluginLogEntryType.Warn,
                }
            )

            await meta.jobs
                .exportHistoricalEventsV2({
                    ...payload,
                    retriesPerformedSoFar: payload.retriesPerformedSoFar + 1,
                } as ExportHistoricalEventsJobPayload)
                .runIn(nextRetrySeconds, 'seconds')
        } else {
            await processError(hub, pluginConfig, error)
            await stopExport(`exportEvents returned unknown error, stopping export. error=${error}`)
        }
    }

    async function stopExport(message: string, logOverrides: Partial<PluginLogEntry> = {}) {
        await meta.storage.del(EXPORT_PARAMETERS_KEY)
        createLog(message, logOverrides)
    }

    function getTimestampBoundaries(payload: ExportHistoricalEventsUIPayload): TimestampBoundaries {
        const min = new Date(payload.dateFrom)
        const max = new Date(payload.dateTo)

        if (isNaN(min.getTime()) || isNaN(max.getTime())) {
            createLog(`'dateFrom' and 'dateTo' should be timestamps in ISO string format.`, {
                type: PluginLogEntryType.Error,
            })
            throw new Error(`'dateFrom' and 'dateTo' should be timestamps in ISO string format.`)
        }
        return { min, max }
    }

    function retryDelaySeconds(retriesPerformedSoFar: number): number {
        return 2 ** retriesPerformedSoFar * 3
    }

    function shouldResume(status: ExportChunkStatus, now: number): boolean {
        // When a export hasn't updated in 10 minutes plus whatever time is spent on retries, it's likely already timed out or died
        // Note that status updates happen every time the export makes _any_ progress
        return now >= status.statusTime + TEN_MINUTES + retryDelaySeconds(status.retriesPerformedSoFar + 1) * 1000
    }

    function nextCursor(payload: ExportHistoricalEventsJobPayload, eventCount: number): OffsetParams {
        // More on the same time window
        if (eventCount === EVENTS_PER_RUN) {
            return {
                timestampCursor: payload.timestampCursor,
                fetchTimeInterval: payload.fetchTimeInterval,
                offset: payload.offset + EVENTS_PER_RUN,
            }
        }

        const nextCursor = payload.timestampCursor + payload.fetchTimeInterval
        let nextFetchInterval = payload.fetchTimeInterval
        // If we're fetching too small of a window at a time, increase window to fetch
        if (payload.offset === 0 && eventCount < EVENTS_PER_RUN * 0.5) {
            nextFetchInterval = Math.min(Math.floor(payload.fetchTimeInterval * 1.2), TWELVE_HOURS)
        }
        // If time window seems too large, reduce it
        if (payload.offset > 2 * EVENTS_PER_RUN) {
            nextFetchInterval = Math.max(Math.floor(payload.fetchTimeInterval / 1.2), TEN_MINUTES)
        }

        // If we would end up fetching too many events next time, reduce fetch interval
        if (nextCursor + nextFetchInterval > payload.endTime) {
            nextFetchInterval = payload.endTime - nextCursor
        }

        return {
            timestampCursor: nextCursor,
            fetchTimeInterval: nextFetchInterval,
            offset: 0,
        }
    }

    function getExportDateRange({ dateFrom, dateTo }: ExportParams): Array<[ISOTimestamp, ISOTimestamp]> {
        const result: Array<[ISOTimestamp, ISOTimestamp]> = []
        let date = dateFrom
        while (date < dateTo) {
            let nextDate = DateTime.fromISO(date).toUTC().plus({ days: 1 }).startOf('day').toISO() as ISOTimestamp
            if (nextDate > dateTo) {
                nextDate = dateTo
            }
            result.push([date, nextDate])
            date = nextDate
        }

        return result
    }

    function progressBar(progress: number, length = 20): string {
        const filledBar = Math.round(progress * length)

        const progressBarCompleted = Array.from({ length: filledBar })
            .map(() => '■')
            .join('')
        const progressBarRemaining = Array.from({ length: length - filledBar })
            .map(() => '□')
            .join('')

        return progressBarCompleted + progressBarRemaining
    }

    function dateRange(startTime: number, endTime: number): string {
        return `${new Date(startTime).toISOString()} to ${new Date(endTime).toISOString()}`
    }

    async function getExportParameters(): Promise<ExportParams | null> {
        return (await meta.storage.get(EXPORT_PARAMETERS_KEY, null)) as ExportParams | null
    }

    function createLog(message: string, overrides: Partial<PluginLogEntry> = {}) {
        hub.promiseManager.trackPromise(
            hub.db.queuePluginLogEntry({
                pluginConfig,
                message: message,
                source: PluginLogEntrySource.System,
                type: PluginLogEntryType.Log,
                instanceId: hub.instanceId,
                ...overrides,
            })
        )
    }

    if (isTestEnv()) {
        meta.global._testFunctions = {
            exportHistoricalEvents,
            getTimestampBoundaries,
            nextCursor,
            coordinateHistoricalExport,
            calculateCoordination,
            getExportDateRange,
            progressBar,
            stopExport,
            shouldResume,
        }
    }
}
