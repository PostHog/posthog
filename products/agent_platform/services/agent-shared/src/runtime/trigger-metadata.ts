/**
 * Typed `agent_session.trigger_metadata`. Discriminated on `kind`, parsed once
 * at the persistence boundary (`pg-queue` `rowToSession`) so readers narrow on
 * `kind` instead of re-validating a loose bag.
 */

import { z } from 'zod'

export const TriggerMetadataSchema = z.discriminatedUnion('kind', [
    z.object({
        kind: z.literal('chat'),
        // Client tool ids the connecting client can fulfil this session (from the
        // /run body). The runner exposes a `kind:'client'` spec tool to the model
        // only if its id is listed here.
        supported_client_tools: z.array(z.string()).optional(),
    }),
    z.object({
        kind: z.literal('slack'),
        workspace_id: z.string(),
        channel: z.string(),
        ts: z.string(),
        thread_ts: z.string(),
    }),
    z.object({
        kind: z.literal('cron'),
        cron_name: z.string(),
        schedule: z.string(),
        fired_at: z.string(),
        manual: z.boolean().optional(),
    }),
    z.object({ kind: z.literal('webhook') }),
    z.object({ kind: z.literal('mcp') }),
])

export type TriggerMetadata = z.infer<typeof TriggerMetadataSchema>

export type SlackTriggerMetadata = Extract<TriggerMetadata, { kind: 'slack' }>

/** Validate a stored row's `trigger_metadata`; unknown/missing/malformed → null. */
export function parseTriggerMetadata(raw: unknown): TriggerMetadata | null {
    const parsed = TriggerMetadataSchema.safeParse(raw)
    return parsed.success ? parsed.data : null
}
