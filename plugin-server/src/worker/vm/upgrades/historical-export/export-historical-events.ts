import { PluginEvent, PluginMeta, RetryError } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'

import {
    Hub,
    JobSpec,
    PluginConfig,
    PluginConfigVMInternalResponse,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginTask,
    PluginTaskType,
} from '../../../../types'
import { fetchEventsForInterval } from '../utils/fetchEventsForInterval'
import {
    ExportHistoricalEventsJobPayload,
    ExportHistoricalEventsUpgrade,
    fetchTimestampBoundariesForTeam,
} from '../utils/utils'

const TEN_MINUTES = 1000 * 60 * 10
const EVENTS_TIME_INTERVAL = TEN_MINUTES
const EVENTS_PER_RUN = 500

const TIMESTAMP_CURSOR_KEY = 'timestamp_cursor'
const MAX_UNIX_TIMESTAMP_KEY = 'max_timestamp'
const MIN_UNIX_TIMESTAMP_KEY = 'min_timestamp'
const EXPORT_RUNNING_KEY = 'is_export_running'
const RUN_EVERY_MINUTE_LAST_RUN_KEY = 'run_every_minute_last'
const BATCH_ID_CURSOR_KEY = 'batch_id'
const OLD_TIMESTAMP_CURSOR_KEY = 'old_timestamp_cursor'

const INTERFACE_JOB_NAME = 'Export historical events'

const JOB_SPEC: JobSpec = {
    payload: {
        dateFrom: {
            title: 'Export start date',
            type: 'date',
            required: true,
        },
        dateTo: {
            title: 'Export end date',
            type: 'date',
            required: true,
        },
    },
}

export function addHistoricalEventsExportCapability(
    hub: Hub,
    pluginConfig: PluginConfig,
    response: PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgrade>>
): void {
    const { methods, tasks, meta } = response

    const currentPublicJobs = pluginConfig.plugin?.public_jobs || {}

    // If public job hasn't been registered or has changed, update it!
    if (
        Object.keys(currentPublicJobs[INTERFACE_JOB_NAME]?.payload || {}).length !==
        Object.keys(JOB_SPEC.payload!).length
    ) {
        hub.promiseManager.trackPromise(
            hub.db.addOrUpdatePublicJob(pluginConfig.plugin_id, INTERFACE_JOB_NAME, JOB_SPEC)
        )
    }

    const oldSetupPlugin = methods.setupPlugin

    const oldRunEveryMinute = tasks.schedule.runEveryMinute

    methods.setupPlugin = async () => {
        await meta.utils.cursor.init(BATCH_ID_CURSOR_KEY)

        const storedTimestampCursor = await meta.storage.get(TIMESTAMP_CURSOR_KEY, null)
        await meta.storage.set(OLD_TIMESTAMP_CURSOR_KEY, storedTimestampCursor || 0)
        await meta.storage.set(RUN_EVERY_MINUTE_LAST_RUN_KEY, Date.now() + TEN_MINUTES)

        await oldSetupPlugin?.()
    }

    tasks.schedule.runEveryMinute = {
        name: 'runEveryMinute',
        type: PluginTaskType.Schedule,
        exec: async () => {
            await oldRunEveryMinute?.exec?.()

            const lastRun = await meta.storage.get(RUN_EVERY_MINUTE_LAST_RUN_KEY, 0)
            const exportShouldBeRunning = await meta.storage.get(EXPORT_RUNNING_KEY, false)

            const have10MinutesPassed = Date.now() - Number(lastRun) < TEN_MINUTES

            // only run every 10 minutes _if_ an export is in progress
            if (!exportShouldBeRunning || !have10MinutesPassed) {
                return
            }

            const oldTimestampCursor = await meta.storage.get(OLD_TIMESTAMP_CURSOR_KEY, 0)
            const currentTimestampCursor = await meta.storage.get(TIMESTAMP_CURSOR_KEY, 0)

            // if the cursor hasn't been incremented after 10 minutes that means we didn't pick up from
            // where we left off  automatically after a restart, or something else has gone wrong
            // thus, kick off a new export chain with a new batchId
            if (exportShouldBeRunning && oldTimestampCursor === currentTimestampCursor) {
                const batchId = await meta.utils.cursor.increment(BATCH_ID_CURSOR_KEY)
                createLog(`Restarting export after noticing inactivity. Batch ID: ${batchId}`)
                await meta.jobs
                    .exportHistoricalEvents({ retriesPerformedSoFar: 0, incrementTimestampCursor: true, batchId })
                    .runNow()
            }

            // set the old timestamp cursor to the current one so we can see if it changed in 10 minutes
            await meta.storage.set(OLD_TIMESTAMP_CURSOR_KEY, currentTimestampCursor)

            await meta.storage.set(RUN_EVERY_MINUTE_LAST_RUN_KEY, Date.now())
        },

        // :TRICKY: We don't want to track app metrics for runEveryMinute for historical exports _unless_ plugin also has `runEveryMinute`
        __ignoreForAppMetrics: !oldRunEveryMinute || !!oldRunEveryMinute.__ignoreForAppMetrics,
    }

    tasks.job['exportHistoricalEvents'] = {
        name: 'exportHistoricalEvents',
        type: PluginTaskType.Job,
        exec: (payload) => meta.global.exportHistoricalEvents(payload as ExportHistoricalEventsJobPayload),
    }

    tasks.job[INTERFACE_JOB_NAME] = {
        name: INTERFACE_JOB_NAME,
        type: PluginTaskType.Job,
        // TODO: Accept timestamp as payload
        exec: async (payload: ExportHistoricalEventsJobPayload) => {
            // only let one export run at a time
            const exportAlreadyRunning = await meta.storage.get(EXPORT_RUNNING_KEY, false)
            if (exportAlreadyRunning) {
                return
            }

            await meta.storage.set(RUN_EVERY_MINUTE_LAST_RUN_KEY, Date.now() + TEN_MINUTES)
            await meta.storage.set(EXPORT_RUNNING_KEY, true)

            // get rid of all state pertaining to a previous run
            await meta.storage.del(TIMESTAMP_CURSOR_KEY)
            await meta.storage.del(MAX_UNIX_TIMESTAMP_KEY)
            await meta.storage.del(MIN_UNIX_TIMESTAMP_KEY)
            meta.global.maxTimestamp = null
            meta.global.minTimestamp = null

            await meta.global.initTimestampsAndCursor(payload)

            const batchId = await meta.utils.cursor.increment(BATCH_ID_CURSOR_KEY)

            await meta.jobs
                .exportHistoricalEvents({ retriesPerformedSoFar: 0, incrementTimestampCursor: true, batchId: batchId })
                .runNow()
        },
    } as unknown as PluginTask // :KLUDGE: Work around typing limitations

    meta.global.exportHistoricalEvents = async (payload: ExportHistoricalEventsJobPayload): Promise<void> => {
        if (payload.retriesPerformedSoFar >= 15) {
            // create some log error here
            return
        }

        // this is handling for duplicates when the plugin server restarts
        const currentBatchId = await meta.storage.get(BATCH_ID_CURSOR_KEY, 0)
        if (currentBatchId !== payload.batchId) {
            return
        }

        let timestampCursor = payload.timestampCursor
        let intraIntervalOffset = payload.intraIntervalOffset ?? 0

        // this ensures minTimestamp and timestampLimit are not null
        // each thread will set them the first time they run this job
        // we do this to prevent us from doing 2 additional queries
        // to postgres each time the job runs
        await meta.global.setTimestampBoundaries()

        // This is the first run OR we're done with an interval
        if (payload.incrementTimestampCursor || !timestampCursor) {
            // Done with a timestamp interval, reset offset
            intraIntervalOffset = 0

            // This ensures we never process an interval twice
            const incrementedCursor = await meta.utils.cursor.increment(TIMESTAMP_CURSOR_KEY, EVENTS_TIME_INTERVAL)

            meta.global.updateProgressBar(incrementedCursor)

            timestampCursor = Number(incrementedCursor)
        }

        if (timestampCursor > meta.global.maxTimestamp!) {
            await meta.storage.del(EXPORT_RUNNING_KEY)
            createLog(`Done exporting all events`)
            return
        }

        let events: PluginEvent[] = []

        let fetchEventsError: Error | unknown | null = null
        try {
            events = await fetchEventsForInterval(
                hub.db,
                pluginConfig.team_id,
                new Date(timestampCursor),
                intraIntervalOffset,
                EVENTS_TIME_INTERVAL,
                EVENTS_PER_RUN
            )
        } catch (error) {
            fetchEventsError = error
            Sentry.captureException(error)
        }

        let exportEventsError: Error | unknown | null = null

        if (fetchEventsError) {
            await meta.storage.del(EXPORT_RUNNING_KEY)
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
                `Failed processing events ${intraIntervalOffset}-${intraIntervalOffset + events.length} from ${new Date(
                    timestampCursor
                ).toISOString()} to ${new Date(
                    timestampCursor + EVENTS_TIME_INTERVAL
                ).toISOString()}. Retrying in ${nextRetrySeconds}s`
            )

            await meta.jobs
                .exportHistoricalEvents({
                    intraIntervalOffset,
                    timestampCursor,
                    retriesPerformedSoFar: payload.retriesPerformedSoFar + 1,
                })
                .runIn(nextRetrySeconds, 'seconds')
        } else if (!exportEventsError) {
            const incrementTimestampCursor = events.length === 0

            await meta.jobs
                .exportHistoricalEvents({
                    timestampCursor,
                    incrementTimestampCursor,
                    retriesPerformedSoFar: 0,
                    intraIntervalOffset: intraIntervalOffset + EVENTS_PER_RUN,
                    batchId: payload.batchId,
                })
                .runIn(1, 'seconds')
        }

        if (events.length > 0) {
            createLog(
                `Successfully processed events ${intraIntervalOffset}-${
                    intraIntervalOffset + events.length
                } from ${new Date(timestampCursor).toISOString()} to ${new Date(
                    timestampCursor + EVENTS_TIME_INTERVAL
                ).toISOString()}.`
            )
        }
    }

    // initTimestampsAndCursor decides what timestamp boundaries to use before
    // the export starts. if a payload is passed with boundaries, we use that,
    // but if no payload is specified, we use the boundaries determined at setupPlugin
    meta.global.initTimestampsAndCursor = async (payload?: ExportHistoricalEventsJobPayload) => {
        // initTimestampsAndCursor will only run on **one** thread, because of our guard against
        // multiple exports. as a result, we need to set the boundaries on postgres, and
        // only set them in global when the job runs, so all threads have global state in sync

        // Fetch the max and min timestamps for a team's events
        const timestampBoundaries = await fetchTimestampBoundariesForTeam(hub.db, pluginConfig.team_id, '_timestamp')

        if (payload && payload.dateFrom) {
            try {
                const dateFrom = new Date(payload.dateFrom).getTime()
                await meta.utils.cursor.init(TIMESTAMP_CURSOR_KEY, dateFrom - EVENTS_TIME_INTERVAL)
                await meta.storage.set(MIN_UNIX_TIMESTAMP_KEY, dateFrom)
            } catch (error) {
                createLog(`'dateFrom' should be an timestamp in ISO string format.`)
                throw error
            }
        } else {
            // no timestamp override specified via the payload, default to the first event ever ingested
            if (!timestampBoundaries) {
                throw new Error(
                    `Unable to determine the lower timestamp bound for the export automatically. Please specify a 'dateFrom' value.`
                )
            }

            const dateFrom = timestampBoundaries.min.getTime()
            await meta.utils.cursor.init(TIMESTAMP_CURSOR_KEY, dateFrom - EVENTS_TIME_INTERVAL)
            await meta.storage.set(MIN_UNIX_TIMESTAMP_KEY, dateFrom)
        }

        if (payload && payload.dateTo) {
            try {
                await meta.storage.set(MAX_UNIX_TIMESTAMP_KEY, new Date(payload.dateTo).getTime())
            } catch (error) {
                createLog(`'dateTo' should be an timestamp in ISO string format.`)
                throw error
            }
        } else {
            // no timestamp override specified via the payload, default to the last event before the plugin was enabled
            if (!timestampBoundaries) {
                throw new Error(
                    `Unable to determine the upper timestamp bound for the export automatically. Please specify a 'dateTo' value.`
                )
            }
            await meta.storage.set(MAX_UNIX_TIMESTAMP_KEY, timestampBoundaries.max.getTime())
        }
    }

    // this ensures we have the global object correctly set on every thread
    // without having to always do a postgres query when an export job for an
    // inteval is triggered
    meta.global.setTimestampBoundaries = async () => {
        if (!meta.global.maxTimestamp) {
            const storedTimestampLimit = await meta.storage.get(MAX_UNIX_TIMESTAMP_KEY, null)
            meta.global.maxTimestamp = Number(storedTimestampLimit)
        }

        if (!meta.global.minTimestamp) {
            const storedMinTimestamp = await meta.storage.get(MIN_UNIX_TIMESTAMP_KEY, null)
            meta.global.minTimestamp = Number(storedMinTimestamp)
        }
    }

    meta.global.updateProgressBar = (incrementedCursor) => {
        const progressNumerator = incrementedCursor - meta.global.minTimestamp!
        const progressDenominator = meta.global.maxTimestamp! - meta.global.minTimestamp!

        const progress = progressDenominator === 0 ? 20 : Math.round(progressNumerator / progressDenominator) * 20
        const percentage = Math.round((1000 * progressNumerator) / progressDenominator) / 10

        const progressBarCompleted = Array.from({ length: progress })
            .map(() => '■')
            .join('')
        const progressBarRemaining = Array.from({ length: 20 - progress })
            .map(() => '□')
            .join('')
        createLog(`Export progress: ${progressBarCompleted}${progressBarRemaining} (${percentage}%)`)
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
}
