import { Hub } from '../src/types'
import { defaultConfig, formatConfigHelp } from './config/config'
import { healthcheckWithExit } from './healthcheck'
import { initApp } from './init'
import { GraphileWorker } from './main/graphile-worker/graphile-worker'
import { startPluginsServer } from './main/pluginsServer'
import { Status } from './utils/status'
import { makePiscina } from './worker/piscina'

const { version } = require('../package.json')
const { argv } = process

enum AlternativeMode {
    Help = 'HELP',
    Version = 'VRSN',
    Healthcheck = 'HLTH',
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
    case AlternativeMode.Migrate:
        initApp(defaultConfig)

        status.info(`🔗`, `Attempting to connect to Graphile Worker to run migrations`)
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
        void startPluginsServer(defaultConfig, makePiscina)
        break
}
