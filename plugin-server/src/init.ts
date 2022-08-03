import { initSentry } from './sentry'
import { PluginsServerConfig } from './types'
import { setLogLevel } from './utils/utils'

// Code that runs on app start, in both the main and worker threads
export function initApp(config: PluginsServerConfig): void {
    setLogLevel(config.LOG_LEVEL)
    initSentry(config)
}
