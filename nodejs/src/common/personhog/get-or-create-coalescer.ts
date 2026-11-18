import { Code, ConnectError } from '@connectrpc/connect'
import { Counter, Histogram } from 'prom-client'

import {
    GetOrCreatePersonEntry,
    GetOrCreatePersonOutcome,
    IDENTITY_BATCH_SIZE,
    PersonhogIdentityOperations,
    getOrCreateEntryBytes,
} from './identity'
import { timedGrpc } from './metrics'

const batchFlushesTotal = new Counter({
    name: 'personhog_get_or_create_batch_flushes_total',
    help: 'Batched get-or-create calls sent, by what closed the batch',
    labelNames: ['client', 'reason'],
})

const batchSize = new Histogram({
    name: 'personhog_get_or_create_batch_size',
    help: 'Entries per batched get-or-create call',
    labelNames: ['client'],
    buckets: [1, 2, 5, 10, 25, 50, 100, 250],
})

/** The batch call itself failed, so no entry got an answer. */
export class BatchCallFailedError extends Error {
    constructor(public override readonly cause: Error) {
        super(`batched get-or-create call failed: ${cause.message}`)
        this.name = 'BatchCallFailedError'
    }
}

export interface GetOrCreateCoalescerOptions {
    /** How long the first entry waits for batchmates before the batch is sent. */
    windowMs: number
    maxBatchSize: number
    /** Entry bytes one batch holds. Keep it under the request size limits of the client and the router. */
    maxBatchBytes: number
    clientLabel: string
}

interface Waiter {
    entry: GetOrCreatePersonEntry
    resolve: (outcome: GetOrCreatePersonOutcome) => void
    reject: (error: Error) => void
}

interface Batch {
    waiters: Waiter[]
    bytes: number
    timer: NodeJS.Timeout | null
}

/** Batches are kept per caller tag because the tag travels as a request header. */
export class GetOrCreateCoalescer {
    private readonly pending = new Map<string, Batch>()

    constructor(
        private readonly identity: Pick<PersonhogIdentityOperations, 'getOrCreatePersonsByDistinctIds'>,
        private readonly options: GetOrCreateCoalescerOptions
    ) {
        if (!Number.isInteger(options.maxBatchSize) || options.maxBatchSize < 1) {
            throw new Error(`get-or-create batch size must be an integer >= 1, got ${options.maxBatchSize}`)
        }
        if (options.maxBatchSize > IDENTITY_BATCH_SIZE) {
            throw new Error(
                `get-or-create batch size ${options.maxBatchSize} exceeds the service cap ${IDENTITY_BATCH_SIZE}`
            )
        }
        if (!Number.isInteger(options.maxBatchBytes) || options.maxBatchBytes < 1) {
            throw new Error(`get-or-create batch bytes must be an integer >= 1, got ${options.maxBatchBytes}`)
        }
        if (!Number.isFinite(options.windowMs) || options.windowMs < 0) {
            throw new Error(`get-or-create batch window must be >= 0 ms, got ${options.windowMs}`)
        }
    }

    submit(entry: GetOrCreatePersonEntry, callerTag: string = ''): Promise<GetOrCreatePersonOutcome> {
        return new Promise((resolve, reject) => {
            const bytes = getOrCreateEntryBytes(entry)
            let batch = this.pending.get(callerTag)
            if (batch !== undefined && batch.bytes + bytes > this.options.maxBatchBytes) {
                this.flush(callerTag, 'bytes')
                batch = undefined
            }
            if (batch === undefined) {
                batch = { waiters: [], bytes: 0, timer: null }
                this.pending.set(callerTag, batch)
            }
            batch.waiters.push({ entry, resolve, reject })
            batch.bytes += bytes
            if (batch.waiters.length >= this.options.maxBatchSize) {
                this.flush(callerTag, 'size')
                return
            }
            if (batch.timer === null) {
                batch.timer = setTimeout(() => this.flush(callerTag, 'window'), this.options.windowMs)
            }
        })
    }

    private flush(callerTag: string, reason: 'size' | 'bytes' | 'window'): void {
        const batch = this.pending.get(callerTag)
        if (batch === undefined) {
            return
        }
        this.pending.delete(callerTag)
        if (batch.timer !== null) {
            clearTimeout(batch.timer)
        }
        batchFlushesTotal.inc({ client: this.options.clientLabel, reason })
        batchSize.observe({ client: this.options.clientLabel }, batch.waiters.length)
        void this.dispatch(batch.waiters, callerTag)
    }

    private async dispatch(waiters: Waiter[], callerTag: string): Promise<void> {
        let results
        try {
            results = await timedGrpc(this.options.clientLabel, 'getOrCreatePersonsByDistinctIds', () =>
                this.identity.getOrCreatePersonsByDistinctIds(
                    waiters.map((waiter) => waiter.entry),
                    callerTag || undefined
                )
            )
        } catch (error) {
            const failure = new BatchCallFailedError(error instanceof Error ? error : new Error(String(error)))
            waiters.forEach((waiter) => waiter.reject(failure))
            return
        }
        if (results.length !== waiters.length) {
            const failure = this.malformed(`expected ${waiters.length} results, got ${results.length}`)
            waiters.forEach((waiter) => waiter.reject(failure))
            return
        }
        waiters.forEach((waiter, index) => {
            const result = results[index]
            if (result.teamId !== waiter.entry.teamId || result.distinctId !== waiter.entry.distinctId) {
                waiter.reject(this.malformed(`result ${index} answers a different key`))
            } else if (result.error !== undefined) {
                waiter.reject(result.error)
            } else {
                waiter.resolve(result.outcome)
            }
        })
    }

    /** Retryable, so the caller's next attempt goes down the singular path. */
    private malformed(detail: string): BatchCallFailedError {
        return new BatchCallFailedError(
            new ConnectError(`malformed batched get-or-create response: ${detail}`, Code.Internal)
        )
    }
}
