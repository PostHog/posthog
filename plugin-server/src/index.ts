import { defaultConfig, formatConfigHelp } from './config/config'
import { healthcheckWithExit } from './healthcheck'
import { initApp } from './init'
import { GraphileQueue } from './main/job-queues/concurrent/graphile-queue'
import { PluginServerMode, startPluginsServer } from './main/pluginsServer'
import { Status } from './utils/status'
import { makePiscina } from './worker/piscina'

const { version } = require('../package.json')
const { argv, env } = process

enum ServerMode {
    Help = 'HELP',
    Version = 'VERSION',
    Healthcheck = 'HEALTH',
    Idle = 'IDLE',
    Migrate = 'MIGRATE',
    Runner = 'RUNNER',
    Ingestion = 'INGESTION',
}

let serverMode: ServerMode = ServerMode.Ingestion

if (argv.includes('--runner') || env.SERVER_MODE === 'runner') {
    serverMode = ServerMode.Runner
} else if (argv.includes('--help') || argv.includes('-h')) {
    serverMode = ServerMode.Help
} else if (argv.includes('--version') || argv.includes('-v')) {
    serverMode = ServerMode.Version
} else if (argv.includes('--healthcheck')) {
    serverMode = ServerMode.Healthcheck
} else if (argv.includes('--migrate')) {
    serverMode = ServerMode.Migrate
} else if (defaultConfig.PLUGIN_SERVER_IDLE) {
    serverMode = ServerMode.Idle
}

const status = new Status(serverMode)

status.info('⚡', `@posthog/plugin-server v${version}`)

switch (serverMode) {
    case ServerMode.Version:
        break
    case ServerMode.Help:
        status.info('⚙️', `Supported configuration environment variables:\n${formatConfigHelp(7)}`)
        break
    case ServerMode.Healthcheck:
        void healthcheckWithExit()
        break
    case ServerMode.Idle:
        status.info('💤', `Disengaging this plugin server instance due to the PLUGIN_SERVER_IDLE env var...`)
        setInterval(() => {
            status.info('💤', 'Plugin server still disengaged with PLUGIN_SERVER_IDLE...')
        }, 30_000)
        break
    case ServerMode.Migrate:
        const isGraphileEnabled = defaultConfig.JOB_QUEUES.split(',')
            .map((s) => s.trim())
            .includes('graphile')

        if (!isGraphileEnabled) {
            status.info('😔', 'Graphile job queues not enabled. Nothing to migrate.')
            process.exit(0)
        }

        initApp(defaultConfig)

        status.info(`🔗`, `Attempting to connect to Graphile job queue to run migrations`)
        void (async function () {
            try {
                const graphile = new GraphileQueue(defaultConfig)
                await graphile.migrate()
                status.info(`✅`, `Graphile migrations are now up to date!`)
                await graphile.disconnectProducer()
                process.exit(0)
            } catch (error) {
                status.error('🔴', 'Error running migrations for Graphile Worker!\n', error)
                process.exit(1)
            }
        })()
        break
    case ServerMode.Runner:
        initApp(defaultConfig)
        void startPluginsServer(defaultConfig, makePiscina, PluginServerMode.Runner) // void the returned promise
    default:
        initApp(defaultConfig)
        void startPluginsServer(defaultConfig, makePiscina) // void the returned promise
        break
}
