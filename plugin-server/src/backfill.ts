import { DateTime, Duration, Interval } from 'luxon'
import assert from 'node:assert/strict'

import { defaultConfig } from './config/config'
import { initApp } from './init'
import { Hub, RawClickHouseEvent, TimestampFormat } from './types'
import { DB } from './utils/db/db'
import { createHub } from './utils/db/hub'
import { formPluginEvent } from './utils/event'
import { Status } from './utils/status'
import { castTimestampToClickhouseFormat } from './utils/utils'
import { PersonState } from './worker/ingestion/person-state'

const status = new Status('backfill')

export async function startBackfill() {
    // This mode can be used as an nodejs counterpart to the django management commands, for incident remediation.
    // Add your logic to the runBackfill function and run it:
    //   - locally with: cd plugin-server && pnpm start:dev -- --backfill
    //   - in a toolbox pod with: node ./plugin-server/dist/index.js -- --backfill

    defaultConfig.PLUGIN_SERVER_MODE = null // Disable all consuming capabilities
    const noCapability = {}
    initApp(defaultConfig)
    const [hub, closeHub] = await createHub(defaultConfig, noCapability)
    status.info('🏁', 'Bootstraping done, starting to backfill')

    await runBackfill(hub)

    // Gracefully tear down the clients.
    status.info('🏁', 'Backfill done, starting shutdown')
    await closeHub()
}

async function runBackfill(hub: Hub) {
    const lower_bound = DateTime.fromISO(process.env.BACKFILL_START!)
    assert.ok(lower_bound.isValid, 'BACKFILL_START is an invalid time: ' + lower_bound.invalidReason)
    const upper_bound = DateTime.fromISO(process.env.BACKFILL_END!)
    assert.ok(upper_bound.isValid, 'BACKFILL_END is an invalid time: ' + upper_bound.invalidReason)
    const lower_bound_ts = DateTime.fromISO(process.env.BACKFILL_START_TS!)
    assert.ok(lower_bound_ts.isValid, 'BACKFILL_START_TS is an invalid time: ' + lower_bound_ts.invalidReason)
    const upper_bound_ts = DateTime.fromISO(process.env.BACKFILL_END_TS!)
    assert.ok(upper_bound_ts.isValid, 'BACKFILL_END_TS is an invalid time: ' + upper_bound_ts.invalidReason)
    const step = Duration.fromISO(process.env.BACKFILL_STEP_INTERVAL!)
    assert.ok(step.isValid, 'BACKFILL_STEP_INTERVAL is an invalid duration: ' + step.invalidReason)

    status.info('🕰', 'Running backfill with the following bounds', {
        lower_bound,
        upper_bound,
        lower_bound_ts,
        upper_bound_ts,
        step,
    })

    let interrupted = false
    process.on('SIGINT', function () {
        interrupted = true
    })

    const windows = Interval.fromDateTimes(lower_bound, upper_bound).splitBy(step)
    for (const window of windows) {
        status.info('🕰', 'Processing events in window', {
            window,
        })

        const events = await retrieveEvents(hub.db, window, lower_bound_ts, upper_bound_ts)
        await handleBatch(hub.db, events)

        status.info('✅', 'Successfully processed events in window', {
            window,
        })
        if (interrupted) {
            status.info('🛑', 'Stopping processing due to SIGINT')
            break
        }
    }
}

async function retrieveEvents(
    db: DB,
    window: Interval,
    start_ts: DateTime,
    end_ts: DateTime
): Promise<RawClickHouseEvent[]> {
    const chTimestampLower = castTimestampToClickhouseFormat(window.start, TimestampFormat.ClickHouseSecondPrecision)
    const chTimestampHigher = castTimestampToClickhouseFormat(window.end, TimestampFormat.ClickHouseSecondPrecision)
    const chTimestampLowerTS = castTimestampToClickhouseFormat(start_ts, TimestampFormat.ClickHouseSecondPrecision)
    const chTimestampHigherTS = castTimestampToClickhouseFormat(end_ts, TimestampFormat.ClickHouseSecondPrecision)

    // :TODO: Adding tag messes up the return value?
    const fetchEventsQuery = `
        SELECT event,
               uuid,
               team_id,
               distinct_id,
               properties,
               timestamp,
               created_at,
               elements_chain
        FROM events
        WHERE _timestamp >= '${chTimestampLower}'
          AND _timestamp < '${chTimestampHigher}'
          AND timestamp >= '${chTimestampLowerTS}'
          AND timestamp < '${chTimestampHigherTS}'
          AND event IN ('$merge_dangerously', '$create_alias', '$identify')
          AND ((event = '$identify' and JSONExtractString(properties, '$anon_distinct_id') != '') OR
               (event != '$identify' and JSONExtractString(properties, 'alias') != ''))
          AND team_id NOT IN (26188, 31040)
        ORDER BY _timestamp`

    let clickhouseFetchEventsResult: { data: RawClickHouseEvent[] }
    // eslint-disable-next-line prefer-const
    clickhouseFetchEventsResult = await db.clickhouseQuery<RawClickHouseEvent>(fetchEventsQuery)
    return clickhouseFetchEventsResult.data
}

// run merges parallel across teams, non-parallel within teams
async function handleBatch(db: DB, events: RawClickHouseEvent[]): Promise<void> {
    const batches = new Map<number, RawClickHouseEvent[]>()
    for (const event of events) {
        const siblings = batches.get(event.team_id)
        if (siblings) {
            siblings.push(event)
        } else {
            batches.set(event.team_id, [event])
        }
    }
    const batchQueue = Array.from(batches.values())
    status.info('⚙️', 'Processing events', {
        eventCount: events.length,
        batchCount: batchQueue.length,
    })

    async function processMicroBatches(batches: RawClickHouseEvent[][]): Promise<void> {
        let currentBatch
        while ((currentBatch = batches.pop()) !== undefined) {
            // Process every message sequentially, stash promises to await on later
            for (const event of currentBatch) {
                await handleEvent(db, event)
            }
        }
        return Promise.resolve()
    }

    const tasks = [...Array(defaultConfig.INGESTION_CONCURRENCY)].map(() => processMicroBatches(batchQueue))
    await Promise.all(tasks)
}

async function handleEvent(db: DB, event: RawClickHouseEvent): Promise<void> {
    // single CH event handlin
    const pluginEvent = formPluginEvent(event)
    const ts: DateTime = DateTime.fromISO(pluginEvent.timestamp as string)
    const personState = new PersonState(pluginEvent, pluginEvent.team_id, pluginEvent.distinct_id, ts, db)
    await personState.handleIdentifyOrAlias()
}
