import { z } from 'zod'

import { parseJSON } from '~/utils/json-parse'

/**
 * Cyclotron queue name for the batch audience resolver. Plain FIFO (no
 * fair-dequeue) — the resolver self-requeues after each page so concurrent
 * batches naturally rotate page-by-page under FIFO.
 */
export const HOGFLOW_BATCH_RESOLVE_QUEUE = 'hogflow_batch_resolve' as const

/**
 * Zod schema for resolver state. Used to validate the BYTEA blob on every
 * dequeue — a deployed job carrying state written by a previous shape (field
 * renamed, required field added, etc.) fails cleanly at the boundary
 * instead of crashing later with a `Cannot read properties of undefined`.
 *
 * `filter_test_accounts` is the only filter field the resolver actually
 * forwards. `properties` is kept loose (`unknown`) because PostHog's filter
 * shape evolves; we don't want resolver replays to fail because some
 * property entry has a new field the worker doesn't care about.
 */
export const BatchResolverStateSchema = z.object({
    batchJobId: z.string().min(1),
    teamId: z.number().int(),
    hogFlowId: z.string().min(1),
    filters: z.object({
        // Match HogFunctionFilters.properties — each entry is an arbitrary record.
        // Keep it loose so resolver replays don't fail when PostHog adds new
        // property-filter fields the worker doesn't care about.
        properties: z.array(z.record(z.string(), z.any())).optional(),
        filter_test_accounts: z.boolean().optional(),
    }),
    variables: z.record(z.string(), z.unknown()),
    groupTypeIndex: z.number().int().optional(),
    maxAudienceSize: z.number().int().nonnegative(),
    cursor: z.string().nullable(),
    totalEnqueued: z.number().int().nonnegative(),
    pagesProcessed: z.number().int().nonnegative(),
    startedAt: z.string(),
    pendingTerminal: z.enum(['completed', 'failed']).optional(),
})

/**
 * State carried by a single resolver cyclotron job between page executions.
 * Serialized as a JSON Buffer in cyclotron_jobs.state. Each execution reads
 * this, processes one page (~500 persons), and either re-queues itself with
 * an updated state or transitions to the terminal-write phase.
 *
 * Source of truth is `BatchResolverStateSchema`; this type is `z.infer`d
 * so the schema and the type can't drift apart.
 */
export type BatchResolverState = z.infer<typeof BatchResolverStateSchema>

export function serializeResolverState(state: BatchResolverState): Buffer {
    return Buffer.from(JSON.stringify(state))
}

export function deserializeResolverState(buf: Buffer | null): BatchResolverState {
    if (!buf) {
        throw new Error('Resolver job is missing state')
    }
    const parsed: unknown = parseJSON(buf.toString('utf-8'))
    return BatchResolverStateSchema.parse(parsed)
}
