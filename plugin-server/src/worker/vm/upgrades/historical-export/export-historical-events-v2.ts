import { Plugin, PluginEvent, PluginMeta, RetryError } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'

import {
    Hub,
    ISOTimestamp,
    PluginConfig,
    PluginConfigVMInternalResponse,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginTask,
    PluginTaskType,
} from '../../../../types'
import { isTestEnv } from '../../../../utils/env-utils'
import { fetchEventsForInterval, fetchTimestampBoundariesForTeam, TimestampBoundaries } from '../utils/utils'

const TEN_MINUTES = 1000 * 60 * 10
const TWELVE_HOURS = 1000 * 60 * 60 * 12
const EVENTS_TIME_INTERVAL = TEN_MINUTES
const EVENTS_PER_RUN = 500

const EXPORT_RUNNING_KEY = 'is_export_running'

const INTERFACE_JOB_NAME = 'Export historical events V2'

export interface TestFunctions {
    exportHistoricalEvents: (payload: ExportHistoricalEventsJobPayload) => Promise<void>
    getTimestampBoundaries: (payload: ExportHistoricalEventsUIPayload) => Promise<TimestampBoundaries>
    nextFetchTimeInterval: (payload: ExportHistoricalEventsJobPayload, eventCount: number) => number
    coordinateHistoricExport: () => Promise<void>
    calculateCoordination: (
        params: ExportParams,
        done: Array<ISOTimestamp>,
        running: Array<ISOTimestamp>
    ) => Promise<CoordinationUpdate>
    getExportDateRange: (params: ExportParams) => Array<[ISOTimestamp, ISOTimestamp]>
    progressBar: (progress: number, length?: number) => string
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
}

export interface ExportHistoricalEventsUIPayload {
    // Only set starting export from UI
    parallelism?: number
    dateFrom?: string
    dateTo?: string
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
    progress: number
    exportIsDone: boolean
}

export function addHistoricalEventsExportCapabilityV2(
    hub: Hub,
    pluginConfig: PluginConfig,
    response: PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgradeV2>>
): void {
    const { methods, tasks, meta } = response

    const currentPublicJobs = pluginConfig.plugin?.public_jobs || {}

    if (!(INTERFACE_JOB_NAME in currentPublicJobs)) {
        hub.promiseManager.trackPromise(hub.db.addOrUpdatePublicJob(pluginConfig.plugin_id, INTERFACE_JOB_NAME, {}))
    }

    const oldRunEveryMinute = tasks.schedule.runEveryMinute?.exec

    tasks.job[INTERFACE_JOB_NAME] = {
        name: INTERFACE_JOB_NAME,
        type: PluginTaskType.Job,
        // TODO: Accept timestamp as payload
        exec: async (payload: ExportHistoricalEventsUIPayload) => {
            // only let one export run at a time
            const alreadyRunningExport = await getExportParameters()
            if (!!alreadyRunningExport) {
                return
            }

            // :TODO: Clear/invalidate old export storage somehow

            const id = Math.floor(Math.random() * 10000 + 1)
            const parallelism = Number(payload.parallelism ?? 1)
            const boundaries = await getTimestampBoundaries(payload)

            await meta.storage.set(EXPORT_RUNNING_KEY, {
                id,
                parallelism,
                dateFrom: boundaries.min.toISOString(),
                dateTo: boundaries.max.toISOString(),
            } as ExportParams)

            await coordinateHistoricExport()
        },
    } as unknown as PluginTask // :KLUDGE: Work around typing limitations

    tasks.job['exportHistoricalEvents'] = {
        name: 'exportHistoricalEvents',
        type: PluginTaskType.Job,
        exec: (payload) => exportHistoricalEvents(payload as ExportHistoricalEventsJobPayload),
    }

    tasks.schedule.runEveryMinute = {
        name: 'runEveryMinute',
        type: PluginTaskType.Schedule,
        exec: async () => {
            await oldRunEveryMinute?.()
            await coordinateHistoricExport()
        },
    }

    async function exportHistoricalEvents(payload: ExportHistoricalEventsJobPayload): Promise<void> {
        if (payload.retriesPerformedSoFar >= 15) {
            // create some log error here
            return
        }

        // :TODO: Handle task when this export isn't active anymore.
        // :TODO: Handle double-processing somehow?

        if (payload.timestampCursor >= payload.endTime) {
            createLog(`Finished processing events between ${payload.startTime} and ${payload.endTime}`)
            await meta.storage.set(`EXPORT_DATE_STATUS_${payload.startTime}`, {
                done: true,
                progress: 1,
                exportId: payload.exportId,
            })

            return
        }

        await meta.storage.set(`EXPORT_DATE_STATUS_${payload.startTime}`, {
            done: false,
            progress: (payload.timestampCursor - payload.startTime) / (payload.endTime - payload.startTime),
            exportId: payload.exportId,
            // :TODO: Save timestampCursor, use that to skip on restarts occurring
        })

        let events: PluginEvent[] = []

        let fetchEventsError: Error | unknown | null = null
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
            fetchEventsError = error
            Sentry.captureException(error)
        }

        let exportEventsError: Error | unknown | null = null

        if (fetchEventsError) {
            await meta.storage.del(EXPORT_RUNNING_KEY)
            // :TODO: Retries logic.
            createLog(`Failed fetching events. Stopping export - please try again later.`)
            return
        } else {
            if (events.length > 0) {
                try {
                    await methods.exportEvents!(events)
                } catch (error) {
                    exportEventsError = error
                }
            }
        }

        if (exportEventsError instanceof RetryError) {
            const nextRetrySeconds = 2 ** payload.retriesPerformedSoFar * 3

            // "Failed processing events 0-100 from 2021-08-19T12:34:26.061Z to 2021-08-19T12:44:26.061Z. Retrying in 3s"
            createLog(
                `Failed processing events ${payload.offset}-${payload.offset + events.length} from ${new Date(
                    payload.timestampCursor
                ).toISOString()} to ${new Date(
                    payload.timestampCursor + EVENTS_TIME_INTERVAL
                ).toISOString()}. Retrying in ${nextRetrySeconds}s`
            )

            await meta.jobs
                .exportHistoricalEvents({
                    ...payload,
                    retriesPerformedSoFar: payload.retriesPerformedSoFar + 1,
                } as ExportHistoricalEventsJobPayload)
                .runIn(nextRetrySeconds, 'seconds')
        } else if (!exportEventsError) {
            const incrementCursor = events.length < EVENTS_PER_RUN
            const incrementedTimeCursor = Math.min(payload.endTime, payload.timestampCursor + payload.fetchTimeInterval)

            await meta.jobs
                .exportHistoricalEvents({
                    ...payload,
                    retriesPerformedSoFar: 0,
                    timestampCursor: incrementCursor ? incrementedTimeCursor : payload.timestampCursor,
                    intraIntervalOffset: incrementCursor ? 0 : payload.offset + EVENTS_PER_RUN,
                    fetchTimeInterval: nextFetchTimeInterval(payload, events.length),
                } as ExportHistoricalEventsJobPayload)
                .runIn(1, 'seconds')
        }

        if (events.length > 0) {
            createLog(
                `Successfully processed events ${payload.offset}-${payload.offset + events.length} from ${new Date(
                    payload.timestampCursor
                ).toISOString()} to ${new Date(payload.timestampCursor + EVENTS_TIME_INTERVAL).toISOString()}.`
            )
        }
    }

    async function getTimestampBoundaries(payload: ExportHistoricalEventsUIPayload): Promise<TimestampBoundaries> {
        if (payload && payload.dateFrom && payload.dateTo) {
            try {
                const min = new Date(payload.dateFrom)
                const max = new Date(payload.dateTo)

                return { min, max }
            } catch (error) {
                createLog(`'dateFrom' and 'dateTo' should be timestamps in ISO string format.`)
                throw error
            }
        } else {
            const timestampBoundaries = await fetchTimestampBoundariesForTeam(hub.db, pluginConfig.team_id)

            // no timestamp override specified via the payload, default to the first event ever ingested
            if (!timestampBoundaries) {
                throw new Error(
                    `Unable to determine the timestamp bound for the export automatically. Please specify 'dateFrom'/'dateTo' values.`
                )
            }

            return timestampBoundaries
        }
    }

    function nextFetchTimeInterval(payload: ExportHistoricalEventsJobPayload, eventCount: number): number {
        if (eventCount === EVENTS_PER_RUN) {
            return payload.fetchTimeInterval
        }
        // If we're fetching too small of a window at a time, increase window to fetch
        if (payload.offset === 0 && eventCount < EVENTS_PER_RUN * 0.5) {
            return Math.min(Math.floor(payload.fetchTimeInterval * 1.2), TWELVE_HOURS)
        }
        // If time window seems too large, reduce it
        if (payload.offset > 2) {
            return Math.max(Math.floor(payload.fetchTimeInterval / 1.2), TEN_MINUTES)
        }
        return payload.offset
    }

    async function coordinateHistoricExport() {
        const params = await getExportParameters()

        if (!params) {
            // No export running!
            return
        }

        const { done, running } = (await meta.storage.get(`EXPORT_COORDINATION`, {})) as CoordinationPayload
        const update = await calculateCoordination(params, done || [], running || [])

        if (update.exportIsDone) {
            await meta.storage.del(EXPORT_RUNNING_KEY)
            createLog('Done exporting all events!')
            return
        }
        // :TODO: Handle all done! Unset the EXPORT_RUNNING_KEY
        // :TODO: Log what dates we're kicking off

        createLog(`Export progress: ${progressBar(update.progress)} (${Math.round(1000 * update.progress) / 10})%`)

        if (update.hasChanges) {
            await Promise.all(
                update.toStartRunning.map(async ([startDate, endDate]) => {
                    await meta.jobs
                        .exportHistoricalEvents({
                            timestampCursor: new Date(startDate).getTime(),
                            startTime: new Date(startDate).getTime(),
                            endTime: new Date(endDate).getTime(),
                            offset: 0,
                            retriesPerformedSoFar: 0,
                            exportId: params.id,
                            fetchTimeInterval: EVENTS_TIME_INTERVAL,
                        } as ExportHistoricalEventsJobPayload)
                        .runNow()
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
        const allDates = getExportDateRange(params)

        let hasChanges = false
        const doneDates = new Set(done)
        const runningDates = new Set(running)
        const progressPerDay = 1.0 / allDates.length

        let progress = progressPerDay * done.length
        for (const date of running || []) {
            const dateStatus = (await meta.storage.get(`EXPORT_DATE_STATUS_${date}`, { done: false })) as {
                done: boolean
            }

            if (dateStatus.done) {
                hasChanges = true
                doneDates.add(date)
                runningDates.delete(date)
                progress += progressPerDay
            } else {
                progress += progressPerDay * progress
            }
            // :TODO: Check this is 'stuck' for some reason.
        }

        const toStartRunning: Array<[ISOTimestamp, ISOTimestamp]> = []

        if (runningDates.size < params.parallelism && doneDates.size + runningDates.size < allDates.length) {
            for (const [startDate, endDate] of allDates) {
                if (!doneDates.has(startDate) && !runningDates.has(endDate)) {
                    runningDates.add(startDate)
                    toStartRunning.push([startDate, endDate])
                }
            }
        }

        return {
            hasChanges,
            done: Array.from(doneDates.values()),
            running: Array.from(runningDates.values()),
            toStartRunning,
            progress,
            exportIsDone: doneDates.size === allDates.length,
        }
    }

    function getExportDateRange({ dateFrom, dateTo }: ExportParams): Array<[ISOTimestamp, ISOTimestamp]> {
        const result: Array<[ISOTimestamp, ISOTimestamp]> = []
        let date = dateFrom
        while (date <= dateTo) {
            const nextDate = DateTime.fromISO(date).toUTC().plus({ days: 1 }).toISO() as ISOTimestamp
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

    async function getExportParameters(): Promise<ExportParams | null> {
        return (await meta.storage.get(EXPORT_RUNNING_KEY, null)) as ExportParams | null
    }

    function createLog(message: string, type: PluginLogEntryType = PluginLogEntryType.Log) {
        hub.promiseManager.trackPromise(
            hub.db.queuePluginLogEntry({
                pluginConfig,
                message: `(${hub.instanceId}) ${message}`,
                source: PluginLogEntrySource.System,
                type: type,
                instanceId: hub.instanceId,
            })
        )
    }

    if (isTestEnv()) {
        meta.global._testFunctions = {
            exportHistoricalEvents,
            getTimestampBoundaries,
            nextFetchTimeInterval,
            coordinateHistoricExport,
            calculateCoordination,
            getExportDateRange,
            progressBar,
        }
    }
}
