import { initSentry } from './sentry'
import { PluginsServerConfig } from './types'

// Code that runs on app start, in both the main and worker threads
export function initApp(config: PluginsServerConfig): void {
    initSentry(config)
}
