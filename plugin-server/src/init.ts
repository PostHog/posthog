import * as Pyroscope from '@pyroscope/nodejs'
import { hostname } from 'os'

import { initSentry } from './sentry'
import { PluginsServerConfig } from './types'
import { status } from './utils/status'

// Code that runs on app start, in both the main and worker threads
export function initApp(config: PluginsServerConfig): void {
    initSentry(config)
    initPyroscope(config)
}

export function initPyroscope(config: PluginsServerConfig): void {
    if (config.PYROSCOPE_ADDRESS && config.PYROSCOPE_TOKEN) {
        let tags: Record<string, any> = {}
        try {
            tags = JSON.parse(config.PYROSCOPE_EXTRA_TAGS)
        } catch (error) {
            status.warn('💥', 'Invalid PYROSCOPE_EXTRA_TAGS format:', error)
        } finally {
            tags.pod_name = hostname()
        }
        Pyroscope.init({
            serverAddress: config.PYROSCOPE_ADDRESS,
            authToken: config.PYROSCOPE_TOKEN,
            appName: 'plugin-server-' + config.PLUGIN_SERVER_MODE,
            tags: tags,
        })
    }
}
