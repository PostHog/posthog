import * as Pyroscope from '@pyroscope/nodejs'

import { initSentry } from './sentry'
import { PluginsServerConfig } from './types'

// Code that runs on app start, in both the main and worker threads
export function initApp(config: PluginsServerConfig): void {
    initSentry(config)
    initPyroscope(config)
}

export function initPyroscope(config: PluginsServerConfig): void {
    if (config.PYROSCOPE_ADDRESS && config.PYROSCOPE_TOKEN) {
        Pyroscope.init({
            serverAddress: config.PYROSCOPE_ADDRESS,
            authToken: config.PYROSCOPE_TOKEN,
            appName: 'plugin-server',
            tags: {
                PLUGIN_SERVER_MODE: config.PLUGIN_SERVER_MODE,
            },
        })
    }
}
