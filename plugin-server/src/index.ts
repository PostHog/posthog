import { defaultConfig, formatConfigHelp } from './config/config'
import { healthcheckWithExit } from './healthcheck'
import { initApp } from './init'
import { GraphileQueue } from './main/job-queues/concurrent/graphile-queue'
import { startPluginsServer } from './main/pluginsServer'
import { Status } from './utils/status'
import { makePiscina } from './worker/piscina'

const { version } = require('../package.json')
const { argv } = process

enum AlternativeMode {
    Help = 'HELP',
    Version = 'VRSN',
    Healthcheck = 'HLTH',
    Idle = 'IDLE',
    Migrate = 'MGRT',
}

let alternativeMode: AlternativeMode | undefined
if (argv.includes('--help') || argv.includes('-h')) {
    alternativeMode = AlternativeMode.Help
} else if (argv.includes('--version') || argv.includes('-v')) {
    alternativeMode = AlternativeMode.Version
} else if (argv.includes('--healthcheck')) {
    alternativeMode = AlternativeMode.Healthcheck
} else if (argv.includes('--migrate')) {
    alternativeMode = AlternativeMode.Migrate
} else if (defaultConfig.PLUGIN_SERVER_IDLE) {
    alternativeMode = AlternativeMode.Idle
}

const status = new Status(alternativeMode)

status.info('⚡', `@posthog/plugin-server v${version}`)

switch (alternativeMode) {
    case AlternativeMode.Version:
        break
    case AlternativeMode.Help:
        status.info('⚙️', `Supported configuration environment variables:\n${formatConfigHelp(7)}`)
        break
    case AlternativeMode.Healthcheck:
        void healthcheckWithExit()
        break
    case AlternativeMode.Idle:
        status.info('💤', `Disengaging this plugin server instance due to the PLUGIN_SERVER_IDLE env var...`)
        setInterval(() => {
            status.info('💤', 'Plugin server still disengaged with PLUGIN_SERVER_IDLE...')
        }, 30_000)
        break
    case AlternativeMode.Migrate:
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

    default:
        initApp(defaultConfig)
        void startPluginsServer(defaultConfig, makePiscina) // void the returned promise
        break
}
