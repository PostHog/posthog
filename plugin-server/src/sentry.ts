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
            tracesSampleRate: 1,
        })
    }
}

export function getSpan(): Tracing.Span | undefined {
    return asyncLocalStorage.getStore()
}

export function runInTransaction<T>(transactionContext: TransactionContext, callback: () => Promise<T>): Promise<T> {
    const transaction = Sentry.startTransaction(transactionContext)
    return asyncLocalStorage.run(transaction, async () => {
        try {
            const result = await callback()
            return result
        } finally {
            transaction.finish()
        }
    })
}

export function runInSpan<T>(spanContext: SpanContext, callback: (span?: Span) => Promise<T>): Promise<T> {
    const parentSpan = getSpan()
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
