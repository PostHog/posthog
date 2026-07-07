import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'

// Plain FIFO; resolver self-requeues per page so concurrent batches rotate naturally.
export const HOGFLOW_BATCH_RESOLVE_QUEUE = 'hogflow_batch_resolve' as const

// Caps how many times a single resolver job may retry a transient failure
// (audience fetch or terminal status PUT). Once exhausted in the fetch path
// the resolver flips to `pendingTerminal: 'failed'` so the Django row reaches
// a terminal state; in the terminal-write path the cyclotron job itself
// fails so the janitor can clean it up.
export const MAX_RESOLVER_ATTEMPTS = 5

// Zod-validated on every dequeue so a job written by an older deploy fails
// cleanly at the boundary instead of crashing later in the page logic.
export const BatchResolverStateSchema = z.object({
    batchJobId: z.string().min(1),
    teamId: z.number().int(),
    hogFlowId: z.string().min(1),
    filters: z.object({
        // Each property entry is an arbitrary record — keep loose so resolver
        // replays survive new filter-property fields the worker doesn't read.
        properties: z.array(z.record(z.string(), z.any())).optional(),
        filter_test_accounts: z.boolean().optional(),
    }),
    variables: z.record(z.string(), z.unknown()),
    groupTypeIndex: z.number().int().optional(),
    maxAudienceSize: z.number().int().nonnegative(),
    cursor: z.string().nullable(),
    totalEnqueued: z.number().int().nonnegative(),
    pagesProcessed: z.number().int().nonnegative(),
    // Resets to 0 on each successful page transition. Increments on every
    // retry path (fetch failure, terminal write failure). Old job rows
    // without this field default to 0 via the zod parse.
    attempts: z.number().int().nonnegative().default(0),
    startedAt: z.string(),
    pendingTerminal: z.enum(['completed', 'failed']).optional(),
})

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
