import { initSentry } from './sentry'
import { PluginsServerConfig } from './types'
import { posthog } from './utils/posthog'

// Code that runs on app start, in both the main and worker threads
export async function initApp(config: PluginsServerConfig): Promise<void> {
    initSentry(config)

    if (process.env.NODE_ENV === 'test') {
        await posthog.disable()
    }
}
