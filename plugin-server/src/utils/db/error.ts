import { PluginEvent, PostHogEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { captureException } from '@sentry/node'

import { Hub, PluginConfig, PluginError, PluginLogEntrySource, PluginLogEntryType } from '../../types'

export class DependencyUnavailableError extends Error {
    constructor(message: string, dependencyName: string, error: Error) {
        super(message)
        this.name = 'DependencyUnavailableError'
        this.dependencyName = dependencyName
        this.error = error
    }
    readonly dependencyName: string
    readonly error: Error
    readonly isRetriable = true
}

export class MessageSizeTooLarge extends Error {
    constructor(message: string, error: Error) {
        super(message)
        this.name = 'MessageSizeTooLarge'
        this.error = error
    }
    readonly error: Error
    readonly isRetriable = false
}

export async function processError(
    server: Hub,
    pluginConfig: PluginConfig | null,
    error: Error | string,
    event?: PluginEvent | ProcessedPluginEvent | PostHogEvent | null
): Promise<void> {
    if (!pluginConfig) {
        captureException(new Error('Tried to process error for nonexistent plugin config!'), {
            tags: { team_id: event?.team_id },
        })
        return
    }

    if (error instanceof DependencyUnavailableError) {
        // For errors relating to PostHog dependencies that are unavailable,
        // e.g. Postgres, Kafka, Redis, we don't want to log the error to Sentry
        // but rather bubble this up the stack for someone else to decide on
        // what to do with it.
        throw error
    }

    const pluginError: PluginError =
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

    await server.db.queuePluginLogEntry({
        pluginConfig,
        source: PluginLogEntrySource.Plugin,
        type: PluginLogEntryType.Error,
        message: pluginError.stack ?? pluginError.message,
        instanceId: server.instanceId,
        timestamp: pluginError.time,
    })
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
