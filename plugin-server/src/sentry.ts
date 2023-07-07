import * as Sentry from '@sentry/node'
import { ProfilingIntegration } from '@sentry/profiling-node'
import * as Tracing from '@sentry/tracing'
import { Span, SpanContext, TransactionContext } from '@sentry/types'
import { timestampWithMs } from '@sentry/utils'
import { AsyncLocalStorage } from 'node:async_hooks'

import { PluginsServerConfig } from './types'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

const asyncLocalStorage = new AsyncLocalStorage<Tracing.Span>()

// Code that runs on app start, in both the main and worker threads
export function initSentry(config: PluginsServerConfig): void {
    if (config.SENTRY_DSN) {
        const integrations = []
        if (config.SENTRY_PLUGIN_SERVER_PROFILING_SAMPLE_RATE > 0) {
            integrations.push(new ProfilingIntegration())
        }
        Sentry.init({
            dsn: config.SENTRY_DSN,
            normalizeDepth: 8, // Default: 3
            initialScope: {
                tags: {
                    PLUGIN_SERVER_MODE: config.PLUGIN_SERVER_MODE,
                    DEPLOYMENT: config.CLOUD_DEPLOYMENT,
                },
            },
            integrations,
            tracesSampleRate: config.SENTRY_PLUGIN_SERVER_TRACING_SAMPLE_RATE,
            profilesSampleRate: config.SENTRY_PLUGIN_SERVER_PROFILING_SAMPLE_RATE,
        })
    }
}

export function getSpan(): Tracing.Span | undefined {
    return asyncLocalStorage.getStore()
}

export function runInTransaction<T>(
    transactionContext: TransactionContext,
    callback: () => Promise<T>,
    sampleRateByDuration?: (durationInSeconds: number) => number
): Promise<T> {
    const currentSpan = getSpan()
    if (currentSpan) {
        // In an existing transaction, just start a new span!
        return runInSpan(transactionContext, callback, currentSpan)
    }

    const transaction = Sentry.startTransaction(transactionContext)
    return asyncLocalStorage.run(transaction, async () => {
        try {
            const result = await callback()
            return result
        } finally {
            // :TRICKY: Allow post-filtering some transactions by duration
            const endTimestamp = timestampWithMs()
            const duration = endTimestamp - transaction.startTimestamp
            if (sampleRateByDuration && transaction.sampled) {
                transaction.sampled = Math.random() < sampleRateByDuration(duration)
            }
            transaction.finish(endTimestamp)
        }
    })
}

export function runInSpan<Callback extends (...args: any[]) => any>(
    spanContext: SpanContext,
    callback: Callback,
    parentSpan?: Span
) {
    if (!parentSpan) {
        parentSpan = getSpan()
    }
    if (parentSpan) {
        const span = parentSpan.startChild(spanContext)
        return asyncLocalStorage.run(span, async () => {
            try {
                const result = await callback()
                return result
            } finally {
                span.finish()
            }
        })
    } else {
        return callback()
    }
}
