import { Counter, Gauge, Histogram } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/config'

import { ValueMatcher } from '../../../types'
import { CdpConfig } from '../../config'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationResult,
    CyclotronJobQueueKind,
    CyclotronJobQueueSource,
} from '../../types'

export const cdpJobSizeKb = new Histogram({
    name: 'cdp_cyclotron_job_size_kb',
    help: 'The size in kb of the jobs we are processing',
    buckets: [0, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, Infinity],
    labelNames: ['queue_kind'],
})

export const cdpJobSizeCompressedKb = new Histogram({
    name: 'cdp_cyclotron_job_size_compressed_kb',
    help: 'The size in kb of the compressed jobs we are processing',
    buckets: [0, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, Infinity],
    labelNames: ['queue_kind'],
})

const cdpCyclotronBatchUtilization = new Gauge({
    name: 'cdp_cyclotron_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['queue', 'source'],
})

const cdpCyclotronJobsProcessed = new Counter({
    name: 'cdp_cyclotron_jobs_processed',
    help: 'The number of jobs we are managing to process',
    labelNames: ['queue', 'source'],
})

export const cdpCyclotronUnroutableInvocations = new Counter({
    name: 'cdp_cyclotron_unroutable_invocations',
    help: 'Invocations failed because their target queue has no topic on this cluster. Every increment is a job that cannot run, so alert on any sustained non-zero rate.',
    labelNames: ['queue'],
})

/**
 * Raised when a batch held invocations whose target queue has no topic on this cluster.
 *
 * These are carried out of the produce path instead of being thrown as the raw produce error, so
 * the consumer can record a terminal failure for each one and let the batch commit. A raw throw
 * latches the consumer's fatal-error flag and exits the process, and the offset is never
 * committed, so the restart replays the same message. That stalls the partition for every team on
 * it, indefinitely.
 */
export class UnroutableInvocationsError extends Error {
    constructor(public readonly invocations: CyclotronJobInvocation[]) {
        const queues = [...new Set(invocations.map((x) => x.queue))].join(', ')
        super(`${invocations.length} invocation(s) target queue(s) [${queues}] with no topic on this cluster`)
        this.name = 'UnroutableInvocationsError'
    }
}

/**
 * Records throughput and batch utilization for a consumed batch.
 * `cdp_cyclotron_batch_utilization` is consumed by KEDA to autoscale the cyclotron workers, so this
 * must be called on every batch — including empty ones — so idle workers report zero and can scale down.
 */
export function observeConsumedBatch(params: {
    queue: CyclotronJobQueueKind
    source: CyclotronJobQueueSource
    batchSize: number
    maxBatchSize: number
}): void {
    const { queue, source, batchSize, maxBatchSize } = params
    cdpCyclotronBatchUtilization.labels({ queue, source }).set(maxBatchSize > 0 ? batchSize / maxBatchSize : 0)
    cdpCyclotronJobsProcessed.inc({ queue, source }, batchSize)
}

/**
 * Strip transient data from invocation state before persisting.
 * Groups are always stripped. Person is stripped when stripPerson is true.
 * These are large and easily reloaded by the worker, so we avoid storing them.
 * Returns a new object if modifications are needed, otherwise the original.
 */
export function sanitizeInvocationForPersistence(
    invocation: CyclotronJobInvocation,
    { stripPerson }: { stripPerson?: boolean } = {}
): CyclotronJobInvocation {
    const globals = invocation.state?.globals
    if (!globals) {
        return invocation
    }

    const hasGroups = globals.groups && Object.keys(globals.groups).length > 0
    const hasPerson = stripPerson && globals.person

    if (!hasGroups && !hasPerson) {
        return invocation
    }

    const { groups: _g, person: _p, ...restGlobals } = globals
    const newGlobals: typeof globals = { ...restGlobals }

    if (!hasPerson && globals.person) {
        newGlobals.person = globals.person
    }

    return {
        ...invocation,
        state: {
            ...invocation.state,
            globals: newGlobals,
        },
    }
}

/**
 * Creates a sanitizer that strips transient data before persisting.
 * Call once at construction time, use the returned functions on every queue operation.
 */
export function createInvocationSanitizer(config: Pick<CdpConfig, 'CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS'>) {
    const stripPersonMatcher: ValueMatcher<number> = buildIntegerMatcher(
        config.CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS,
        true
    )

    return {
        sanitizeInvocations(invocations: CyclotronJobInvocation[]): CyclotronJobInvocation[] {
            return invocations.map((inv) =>
                sanitizeInvocationForPersistence(inv, { stripPerson: stripPersonMatcher(inv.teamId) })
            )
        },

        sanitizeResults(results: CyclotronJobInvocationResult[]): CyclotronJobInvocationResult[] {
            return results.map((result) => ({
                ...result,
                invocation: sanitizeInvocationForPersistence(result.invocation, {
                    stripPerson: stripPersonMatcher(result.invocation.teamId),
                }),
            }))
        },
    }
}
