import { getPluginServerCapabilities } from './capabilities'
import { defaultConfig } from './config/config'
import { initApp } from './init'
import { startPluginsServer } from './main/pluginsServer'
import { Status } from './utils/status'

const { version } = require('../package.json')
const { argv } = process

enum AlternativeMode {
    Version = 'VRSN',
    Healthcheck = 'HLTH',
    Backfill = 'BKFL',
}

let alternativeMode: AlternativeMode | undefined
if (argv.includes('--version') || argv.includes('-v')) {
    alternativeMode = AlternativeMode.Version
} else if (argv.includes('--backfill')) {
    alternativeMode = AlternativeMode.Backfill
}

const status = new Status(alternativeMode)

status.info('⚡', `@posthog/plugin-server v${version}`)

switch (alternativeMode) {
    case AlternativeMode.Version:
        break
    default:
        // void the returned promise
        initApp(defaultConfig)
        const capabilities = getPluginServerCapabilities(defaultConfig)
        void startPluginsServer(defaultConfig, capabilities)
        break
}
