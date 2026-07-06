/**
 * Typed `agent_session.trigger_metadata`. Discriminated on `kind`, parsed once
 * at the persistence boundary (`pg-queue` `rowToSession`) so readers narrow on
 * `kind` instead of re-validating a loose bag.
 *
 * Strip-on-read contract: Zod's default `.strip()` mode drops any key not
 * declared in the schema. The dropped keys still live in the JSONB on disk
 * — `rowToSession` never writes the normalized shape back. Two consequences
 * for future contributors:
 *
 *   1. **Every writer must go through this schema.** Don't insert
 *      `trigger_metadata` rows via raw SQL or a typed-as-unknown shortcut;
 *      anything not in the discriminated union becomes a runtime ghost
 *      (visible to JSONB queries, invisible to every reader).
 *   2. **Adding a field is a schema change, not a write-side change.** A
 *      writer stamping `{ kind: 'chat', new_field: '…' }` without adding
 *      `new_field` to this schema gets it silently dropped on first read —
 *      bug class to watch for in PR review.
 *
 * Authors who want a defense-in-depth test that the column is clean can scan
 * `agent_session.trigger_metadata` for unknown keys per `kind`; that test
 * lives at the persistence layer, not here.
 */

import { z } from 'zod'

// Realistic bounds for `supported_client_tools`: agent specs cap at a few dozen
// client tool kinds, and ids follow short snake_case (`focus`, `connect_mcp`).
// Caps stop a misbehaving caller from bloating `agent_session.trigger_metadata`
// JSONB without breaking any legitimate caller.
export const SUPPORTED_CLIENT_TOOLS_MAX_LEN = 64
export const SUPPORTED_CLIENT_TOOL_ID_MAX_LEN = 128

export const TriggerMetadataSchema = z.discriminatedUnion('kind', [
    z.object({
        kind: z.literal('chat'),
        // Client tool ids the connecting client can fulfil this session (from the
        // /run body). The runner exposes a `kind:'client'` spec tool to the model
        // only if its id is listed here.
        // Trim + dedupe at the parse boundary so `supported.includes(t.id)` in
        // build-agent-tools.ts can be an exact-string match. A caller that
        // sent `['focus', ' focus ', 'focus']` collapses to `['focus']`. Trim
        // happens before length validation so a whitespace-only string fails
        // the `min(1)` check rather than slipping through as empty.
        supported_client_tools: z
            .array(
                z
                    .string()
                    .transform((s) => s.trim())
                    .pipe(z.string().min(1).max(SUPPORTED_CLIENT_TOOL_ID_MAX_LEN))
            )
            .max(SUPPORTED_CLIENT_TOOLS_MAX_LEN)
            .transform((xs) => Array.from(new Set(xs)))
            .optional(),
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
