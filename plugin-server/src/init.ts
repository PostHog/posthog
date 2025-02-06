import { PluginsServerConfig } from './types'
import { initSentry } from './utils/sentry'

// Code that runs on app start, in both the main and worker threads
export function initApp(config: PluginsServerConfig): void {
    initSentry(config)
}
