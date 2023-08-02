import { DateTime, Duration, Interval } from 'luxon'
import assert from 'node:assert/strict'

import { getPluginServerCapabilities } from './capabilities'
import { defaultConfig } from './config/config'
import { initApp } from './init'
import { GraphileWorker } from './main/graphile-worker/graphile-worker'
import { startPluginsServer } from './main/pluginsServer'
import { Hub, RawClickHouseEvent } from './types'
import { DB } from './utils/db/db'
import { createHub } from './utils/db/hub'
import { formPluginEvent } from './utils/event'
import { Status } from './utils/status'
import { PersonState } from './worker/ingestion/person-state'
import { makePiscina } from './worker/piscina'

const { version } = require('../package.json')
const { argv } = process

enum AlternativeMode {
    Version = 'VRSN',
    Healthcheck = 'HLTH',
    Migrate = 'MGRT',
    Backfill = 'BKFL',
}

let alternativeMode: AlternativeMode | undefined
if (argv.includes('--version') || argv.includes('-v')) {
    alternativeMode = AlternativeMode.Version
} else if (argv.includes('--migrate')) {
    alternativeMode = AlternativeMode.Migrate
} else if (argv.includes('--backfill')) {
    alternativeMode = AlternativeMode.Backfill
}

const status = new Status(alternativeMode)

status.info('⚡', `@posthog/plugin-server v${version}`)

switch (alternativeMode) {
    case AlternativeMode.Version:
        break
    case AlternativeMode.Migrate:
        initApp(defaultConfig)

        status.info(`🔗`, 'Attempting to connect to Graphile Worker to run migrations')
        void (async function () {
            try {
                const graphileWorker = new GraphileWorker(defaultConfig as Hub)
                await graphileWorker.migrate()
                status.info(`✅`, `Graphile Worker migrations are now up to date!`)
                await graphileWorker.disconnectProducer()
                process.exit(0)
            } catch (error) {
                status.error('🔴', 'Error running migrations for Graphile Worker!\n', error)
                process.exit(1)
            }
        })()
        break
    case AlternativeMode.Backfill:
        void startBackfill()
        break
    default:
        // void the returned promise
        initApp(defaultConfig)
        const capabilities = getPluginServerCapabilities(defaultConfig)
        void startPluginsServer(defaultConfig, makePiscina, capabilities)
        break
}

async function startBackfill() {
    // This mode can be used as an nodejs counterpart to the django management commands, for incident remediation.
    // Add your logic to the runBackfill function and run it:
    //   - locally with: cd plugin-server && pnpm start:dev -- --backfill
    //   - in a toolbox pod with: node ./plugin-server/dist/index.js -- --backfill

    defaultConfig.PLUGIN_SERVER_MODE = null // Disable all consuming capabilities
    const noCapability = {}
    initApp(defaultConfig)
    const [hub, closeHub] = await createHub(defaultConfig, null, noCapability)
    status.info('🏁', 'Bootstraping done, starting to backfill')

    await runBackfill(hub)

    // Gracefully tear down the clients.
    status.info('🏁', 'Backfill done, starting shutdown')
    await closeHub()
}

// eslint-disable-next-line @typescript-eslint/require-await
async function runBackfill(_hub: Hub) {
    const lower_bound = DateTime.fromISO(process.env.BACKFILL_START!)
    assert.ok(lower_bound.isValid, 'BACKFILL_START is an invalid time: ' + lower_bound.invalidReason)
    const upper_bound = DateTime.fromISO(process.env.BACKFILL_END!)
    assert.ok(upper_bound.isValid, 'BACKFILL_END is an invalid time: ' + upper_bound.invalidReason)
    const step = Duration.fromISO(process.env.BACKFILL_STEP_INTERVAL!)
    assert.ok(step.isValid, 'BACKFILL_STEP_INTERVAL is an invalid duration: ' + step.invalidReason)

    status.info('🕰', 'Running backfill with the following bounds', {
        lower_bound,
        upper_bound,
        step,
    })

    const windows = Interval.fromDateTimes(lower_bound, upper_bound).splitBy(step)
    windows.forEach(function (window: Interval) {
        status.info('🕰', 'Processing events in window', {
            window,
        })

        // TODO: process the window

        status.info('✅', 'Successfully processed events in window', {
            window,
        })
    })
}

// TODO: query CH by 10 min chunks from start to end based on envs
// run merges parallel across teams, non-parallel within teams
// status log message when done
// eslint-disable-next-line @typescript-eslint/no-unused-vars
async function handleBatch(db: DB, events: RawClickHouseEvent[]): Promise<void> {
    const eventMap = new Map<number, RawClickHouseEvent[]>()
    for (const event of events) {
        if (eventMap.has(event.team_id)) {
            eventMap.get(event.team_id)?.push(event)
        } else {
            eventMap.set(event.team_id, [event])
        }
    }

    const promises: Promise<void>[] = []
    for (const teamEvents of eventMap.values()) {
        promises.push(handleTeam(db, teamEvents))
    }

    await Promise.all(promises)
}

async function handleTeam(db: DB, events: RawClickHouseEvent[]): Promise<void> {
    for (const event of events) {
        await handleEvent(db, event)
    }
}

async function handleEvent(db: DB, event: RawClickHouseEvent): Promise<void> {
    // single CH event handlin
    const pluginEvent = formPluginEvent(event)
    const ts: DateTime = DateTime.fromISO(pluginEvent.timestamp as string)
    const personState = new PersonState(pluginEvent, pluginEvent.team_id, pluginEvent.distinct_id, ts, db)
    await personState.handleIdentifyOrAlias()
}
