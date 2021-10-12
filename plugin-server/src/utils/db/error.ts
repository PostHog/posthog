import { PluginEvent } from '@posthog/plugin-scaffold'
import { captureException } from '@sentry/minimal'

import { Hub, PluginConfig, PluginError } from '../../types'
import { setError } from './sql'

export async function processError(
    server: Hub,
    pluginConfig: PluginConfig | null,
    error: Error | string,
    event?: PluginEvent | null
): Promise<void> {
    if (!pluginConfig) {
        captureException(new Error('Tried to process error for nonexistent plugin config!'))
        return
    }
    const errorJson: PluginError =
        typeof error === 'string'
            ? {
                  message: error,
                  time: new Date().toISOString(),
              }
            : {
                  message: error.message,
                  time: new Date().toISOString(),
                  name: error.name,
                  stack: error.stack,
                  event: event,
              }

    await setError(server, errorJson, pluginConfig)
}

export async function clearError(server: Hub, pluginConfig: PluginConfig): Promise<void> {
    // running this may causes weird deadlocks with piscina and vms, so avoiding if possible
    if (pluginConfig.error) {
        await setError(server, null, pluginConfig)
    }
}
