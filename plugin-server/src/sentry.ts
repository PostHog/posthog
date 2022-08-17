import * as Sentry from '@sentry/node'
import * as Tracing from '@sentry/tracing'
import { Span, SpanContext, TransactionContext } from '@sentry/types'
import { AsyncLocalStorage } from 'node:async_hooks'

import { PluginsServerConfig } from './types'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

const asyncLocalStorage = new AsyncLocalStorage<Tracing.Span>()

// Code that runs on app start, in both the main and worker threads
export function initSentry(config: PluginsServerConfig): void {
    if (config.SENTRY_DSN) {
        Sentry.init({
            dsn: config.SENTRY_DSN,
            normalizeDepth: 8, // Default: 3
            initialScope: {
                tags: {
                    PLUGIN_SERVER_MODE: config.PLUGIN_SERVER_MODE,
                },
            },
            tracesSampleRate: config.SENTRY_PLUGIN_SERVER_TRACING_SAMPLE_RATE,
        })
    }
}

export function getSpan(): Tracing.Span | undefined {
    return asyncLocalStorage.getStore()
}

export function runInTransaction<T>(
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    transactionContext: TransactionContext,
    callback: () => Promise<T>,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    sampleRateByDuration?: (durationInSeconds: number) => number
): Promise<T> {
    return callback()
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function runInSpan<T>(spanContext: SpanContext, callback: (span?: Span) => Promise<T>): Promise<T> {
    return callback()
}
