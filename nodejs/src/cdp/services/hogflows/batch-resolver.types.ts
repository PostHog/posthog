import { parseJSON } from '~/utils/json-parse'

import type { HogFunctionFilters } from '../../types'

/**
 * Cyclotron queue name for the batch audience resolver. Plain FIFO (no
 * fair-dequeue) — the resolver self-requeues after each page so concurrent
 * batches naturally rotate page-by-page under FIFO.
 */
export const HOGFLOW_BATCH_RESOLVE_QUEUE = 'hogflow_batch_resolve' as const

/**
 * State carried by a single resolver cyclotron job between page executions.
 * Serialized as a JSON Buffer in cyclotron_jobs.state. Each execution reads
 * this, processes one page (~500 persons), and either re-queues itself with
 * an updated state or transitions to the terminal-write phase.
 */
export interface BatchResolverState {
    batchJobId: string // == HogFlowBatchJob.id, == parentRunId on children
    teamId: number
    hogFlowId: string
    filters: Pick<HogFunctionFilters, 'properties' | 'filter_test_accounts'>
    variables: Record<string, unknown>
    groupTypeIndex?: number
    maxAudienceSize: number

    cursor: string | null // null on first page
    totalEnqueued: number
    pagesProcessed: number
    startedAt: string // ISO timestamp

    /**
     * When set, the next execution skips audience fetching and tries to PUT
     * terminal status to Django. The resolver only acks itself after Django
     * acknowledges — so if Django is down, the resolver retries via cyclotron
     * retry semantics until the write goes through.
     *
     * `truncatedAtCount` is only relevant when `pendingTerminal === 'completed'`
     * and the run hit the maxAudienceSize cap (carries the cap data to Django).
     */
    pendingTerminal?: 'completed' | 'failed'
    truncatedAtCount?: number
}

export function serializeResolverState(state: BatchResolverState): Buffer {
    return Buffer.from(JSON.stringify(state))
}

export function deserializeResolverState(buf: Buffer | null): BatchResolverState {
    if (!buf) {
        throw new Error('Resolver job is missing state')
    }
    return parseJSON(buf.toString('utf-8')) as BatchResolverState
}
