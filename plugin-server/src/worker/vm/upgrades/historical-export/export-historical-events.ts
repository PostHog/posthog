import { PluginEvent, PluginMeta, RetryError } from '@posthog/plugin-scaffold'

import {
    Hub,
    MetricMathOperations,
    PluginConfig,
    PluginConfigVMInternalResponse,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginTaskType,
} from '../../../../types'
import { addPublicJobIfNotExists } from '../../utils'
import {
    ExportEventsJobPayload,
    ExportHistoricalEventsUpgrade,
    fetchEventsForInterval,
    fetchTimestampBoundariesForTeam,
} from './utils'

const TEN_MINUTES = 1000 * 60 * 10
const EVENTS_TIME_INTERVAL = TEN_MINUTES
const EVENTS_PER_RUN = 100

const TIMESTAMP_CURSOR_KEY = 'timestamp_cursor'
const MAX_UNIX_TIMESTAMP_KEY = 'max_timestamp'
const MIN_UNIX_TIMESTAMP_KEY = 'min_timestamp'
const EXPORT_RUNNING_KEY = 'is_export_running'
const RUN_EVERY_MINUTE_LAST_RUN_KEY = 'run_every_minute_last'
const BATCH_ID_CURSOR_KEY = 'batch_id'
const OLD_TIMESTAMP_CURSOR_KEY = 'old_timestamp_cursor'

const INTERFACE_JOB_NAME = 'Export historical events'

export async function addHistoricalEventsExportCapability(
    hub: Hub,
    pluginConfig: PluginConfig,
    response: PluginConfigVMInternalResponse<PluginMeta<ExportHistoricalEventsUpgrade>>
): Promise<void> {
    const { methods, tasks, meta } = response

    // we can void this as the job appearing on the interface is not time-sensitive
    await addPublicJobIfNotExists(hub.db, pluginConfig.plugin_id, INTERFACE_JOB_NAME, {})

    const oldSetupPlugin = methods.setupPlugin

    const oldRunEveryMinute = tasks.schedule.runEveryMinute?.exec

    methods.setupPlugin = async () => {
        // Fetch the max and min timestamps for a team's events
        const timestampBoundaries = await fetchTimestampBoundariesForTeam(hub.db, pluginConfig.team_id)

        // make sure we set these boundaries at setupPlugin, because from here on out
        // the new events will already be exported via exportEvents, and we don't want
        // the historical export to duplicate them
        meta.global.timestampBoundariesForTeam = timestampBoundaries

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

            await oldRunEveryMinute?.()
        },
    }

    tasks.job['exportHistoricalEvents'] = {
        name: 'exportHistoricalEvents',
        type: PluginTaskType.Job,
        exec: (payload) => meta.global.exportHistoricalEvents(payload as ExportEventsJobPayload),
    }

    tasks.job[INTERFACE_JOB_NAME] = {
        name: INTERFACE_JOB_NAME,
        type: PluginTaskType.Job,
        // TODO: Accept timestamp as payload
        exec: async (payload) => {
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
    }

    meta.global.exportHistoricalEvents = async (payload): Promise<void> => {
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
        }

        if (payload.retriesPerformedSoFar === 0) {
            const incrementTimestampCursor = events.length === 0

            await meta.jobs
                .exportHistoricalEvents({
                    timestampCursor,
                    incrementTimestampCursor,
                    retriesPerformedSoFar: 0,
                    intraIntervalOffset: intraIntervalOffset + EVENTS_PER_RUN,
                    batchId: payload.batchId,
                })
                .runNow()
        }

        let exportEventsError: Error | unknown | null = null

        if (!fetchEventsError) {
            try {
                await methods.exportEvents!(events)
            } catch (error) {
                exportEventsError = error
            }
        }

        // Retry on every error from "our side" but only on a RetryError from the plugin dev
        if (fetchEventsError || exportEventsError instanceof RetryError) {
            const nextRetrySeconds = 2 ** payload.retriesPerformedSoFar * 3

            // "Failed processing events 0-100 from 2021-08-19T12:34:26.061Z to 2021-08-19T12:44:26.061Z. Retrying in 3s"
            createLog(
                `Failed processing events ${intraIntervalOffset}-${
                    intraIntervalOffset + EVENTS_PER_RUN
                } from ${new Date(timestampCursor).toISOString()} to ${new Date(
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
        }

        createLog(
            `Successfully processed events ${intraIntervalOffset}-${
                intraIntervalOffset + EVENTS_PER_RUN
            } from ${new Date(timestampCursor).toISOString()} to ${new Date(
                timestampCursor + EVENTS_TIME_INTERVAL
            ).toISOString()}.`
        )

        incrementMetric('events_exported', events.length)
    }

    // initTimestampsAndCursor decides what timestamp boundaries to use before
    // the export starts. if a payload is passed with boundaries, we use that,
    // but if no payload is specified, we use the boundaries determined at setupPlugin
    meta.global.initTimestampsAndCursor = async (payload) => {
        // initTimestampsAndCursor will only run on **one** thread, because of our guard against
        // multiple exports. as a result, we need to set the boundaries on postgres, and
        // only set them in global when the job runs, so all threads have global state in sync

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
            if (!meta.global.timestampBoundariesForTeam.min) {
                throw new Error(
                    `Unable to determine the lower timestamp bound for the export automatically. Please specify a 'dateFrom' value.`
                )
            }

            const dateFrom = meta.global.timestampBoundariesForTeam.min.getTime()
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
            if (!meta.global.timestampBoundariesForTeam.max) {
                throw new Error(
                    `Unable to determine the upper timestamp bound for the export automatically. Please specify a 'dateTo' value.`
                )
            }
            await meta.storage.set(MAX_UNIX_TIMESTAMP_KEY, meta.global.timestampBoundariesForTeam.max.getTime())
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

        const progressBarCompleted = Array.from({ length: progress })
            .map((_) => '■')
            .join('')
        const progressBarRemaining = Array.from({ length: 20 - progress })
            .map((_) => '□')
            .join('')
        createLog(`Export progress: ${progressBarCompleted}${progressBarRemaining}`)
    }

    function incrementMetric(metricName: string, value: number) {
        hub.pluginMetricsManager.updateMetric({
            metricName,
            value,
            pluginConfig,
            metricOperation: MetricMathOperations.Increment,
        })
    }

    function createLog(message: string, type: PluginLogEntryType = PluginLogEntryType.Log) {
        void hub.db.queuePluginLogEntry({
            pluginConfig,
            message: `(${hub.instanceId}) ${message}`,
            source: PluginLogEntrySource.System,
            type: type,
            instanceId: hub.instanceId,
        })
    }
}
