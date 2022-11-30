import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { captureException } from '@sentry/node'

import { Hub, PluginConfig, PluginError } from '../../types'
import { setError } from './sql'

export class DependencyUnavailableError extends Error {
    constructor(message: string, dependencyName: string, error: Error) {
        super(message)
        this.name = 'DependencyUnavailableError'
        this.dependencyName = dependencyName
        this.error = error
    }
    readonly dependencyName: string
    readonly error: Error
}

export async function processError(
    server: Hub,
    pluginConfig: PluginConfig | null,
    error: Error | string,
    event?: PluginEvent | ProcessedPluginEvent | null
): Promise<void> {
    if (!pluginConfig) {
        captureException(new Error('Tried to process error for nonexistent plugin config!'))
        return
    }

    if (error instanceof DependencyUnavailableError) {
        // For errors relating to PostHog dependencies that are unavailable,
        // e.g. Postgres, Kafka, Redis, we don't want to log the error to Sentry
        // but rather bubble this up the stack for someone else to decide on
        // what to do with it.
        throw error
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
                  stack: cleanErrorStackTrace(error.stack),
                  event: event,
              }

    await setError(server, errorJson, pluginConfig)
}

export async function clearError(server: Hub, pluginConfig: PluginConfig): Promise<void> {
    // running this may causes weird deadlocks with piscina and vms, so avoiding if possible
    if (pluginConfig.has_error) {
        await setError(server, null, pluginConfig)
    }
}

export function cleanErrorStackTrace(stack: string | undefined): string | undefined {
    if (!stack) {
        return stack
    }

    const lines = stack.split('\n')
    const firstInternalLine = lines.findIndex((line) => line.includes('at __inBindMeta'))
    if (firstInternalLine !== -1) {
        return lines.slice(0, firstInternalLine).join('\n')
    } else {
        return stack
    }
}
