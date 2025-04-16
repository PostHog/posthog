const fs = require('fs')

import * as Sentry from '@sentry/node'
import { Span, SpanContext, TransactionContext } from '@sentry/types'

import { PluginsServerConfig } from '../types'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// Code that runs on app start, in both the main and worker threads
export function initSentry(config: PluginsServerConfig): void {
    let release: string | undefined = undefined
    try {
        // Docker containers should have a commit.txt file in the base directory with the git
        // commit hash used to generate them. `plugin-server` runs from a child directory, so we
        // need to look up one level.
        release = fs.readFileSync('../commit.txt', 'utf8')
    } catch (error) {
        // The release isn't required, it's just nice to have.
    }

    Sentry.init({
        initialScope: {
            tags: {
                PLUGIN_SERVER_MODE: config.PLUGIN_SERVER_MODE,
                DEPLOYMENT: config.CLOUD_DEPLOYMENT,
                PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE: config.PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE,
            },
        },
        release,
    })
}

export function getSpan(): Span | undefined {
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

    return asyncLocalStorage.run(transaction, async () => {
        try {
            const result = await callback()
            return result
        } finally {
            if (sampleRateByDuration) {
            }
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
        return asyncLocalStorage.run(span, async () => {
            const result = await callback()
            return result
        })
    } else {
        return callback()
    }
}
