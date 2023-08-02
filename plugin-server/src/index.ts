import { DateTime } from 'luxon'
import { DB } from 'utils/db/db'
import { formPluginEvent } from 'utils/event'
import { PersonState } from 'worker/ingestion/person-state'

import { Hub, RawClickHouseEvent } from '../src/types'
import { getPluginServerCapabilities } from './capabilities'
import { defaultConfig } from './config/config'
import { initApp } from './init'
import { GraphileWorker } from './main/graphile-worker/graphile-worker'
import { startPluginsServer } from './main/pluginsServer'
import { Status } from './utils/status'
import { makePiscina } from './worker/piscina'

const { version } = require('../package.json')
const { argv } = process

enum AlternativeMode {
    Version = 'VRSN',
    Healthcheck = 'HLTH',
    Migrate = 'MGRT',
}

let alternativeMode: AlternativeMode | undefined
if (argv.includes('--version') || argv.includes('-v')) {
    alternativeMode = AlternativeMode.Version
} else if (argv.includes('--migrate')) {
    alternativeMode = AlternativeMode.Migrate
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

    default:
        // void the returned promise
        initApp(defaultConfig)
        const capabilities = getPluginServerCapabilities(defaultConfig)
        void startPluginsServer(defaultConfig, makePiscina, capabilities)
        break
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
