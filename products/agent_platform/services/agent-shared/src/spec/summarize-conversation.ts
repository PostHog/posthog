/**
 * Cheap session summary helpers. Used by the janitor's /sessions list view to
 * give callers (Django, MCP, debug UIs) a useful glance without paying for the
 * full conversation transcript.
 */

import { AssistantMessageRecord, ConversationMessage, EMPTY_USAGE_TOTAL, SessionUsageTotal } from './spec'

/** @deprecated Use SessionUsageTotal — the 9-field shape persisted on agent_session. */
export type ConversationUsageTotal = SessionUsageTotal

const PREVIEW_MAX = 120

/**
 * Last assistant text block, trimmed to ~120 chars with a trailing "…" when
 * truncated. Returns null when no assistant message has surfaced yet (e.g. the
 * session is still in `queued` or hasn't produced text).
 */
export function lastAssistantTextPreview(
    conversation: ConversationMessage[],
    max: number = PREVIEW_MAX
): string | null {
    for (let i = conversation.length - 1; i >= 0; i--) {
        const m = conversation[i]
        if (m.role !== 'assistant') {
            continue
        }
        const textBlock = m.content.find((c) => c.type === 'text')
        if (!textBlock || typeof textBlock.text !== 'string') {
            continue
        }
        const collapsed = textBlock.text.replace(/\s+/g, ' ').trim()
        // Slice by code points, not UTF-16 code units: a raw `.slice()` can cut
        // an emoji's surrogate pair in half, leaving a lone surrogate that's not
        // valid UTF-8 and blows up downstream JSON serialization (orjson refuses
        // it). `Array.from` splits on full code points, so the truncation can
        // never end mid-character.
        const chars = Array.from(collapsed)
        return chars.length > max ? `${chars.slice(0, max - 1).join('')}…` : collapsed
    }
    return null
}

/**
 * Aggregate token + cost numbers across every assistant message in the
 * conversation. Returns all-zeroes when no assistant has run yet (or when the
 * model didn't report usage — e.g. faux providers in tests).
 *
 * Same shape the runner persists into `agent_session.usage_total` — use this
 * helper for backfill and ad-hoc derivation, but read off the column for
 * live sessions.
 */
export function totalConversationUsage(conversation: ConversationMessage[]): SessionUsageTotal {
    let out: SessionUsageTotal = { ...EMPTY_USAGE_TOTAL }
    for (const m of conversation) {
        if (m.role !== 'assistant' || !m.usage) {
            continue
        }
        out = accumulateUsage(out, m)
    }
    return out
}

/**
 * Fold one assistant message's `usage` into a running total (runner per-turn
 * accumulator + backfill walk). Accumulates tokens but NEVER pi-ai's `cost.*`
 * estimates — cost is owned by the gateway's settled /v1/usage figure, which
 * the driver merges into `cost_total` post-turn. Off the gateway path the row
 * cost stays zero (ingestion prices events from the catalog). Cost fields carry
 * forward unchanged here.
 */
export function accumulateUsage(prev: SessionUsageTotal, msg: AssistantMessageRecord): SessionUsageTotal {
    const usage = msg.usage
    if (!usage) {
        return prev
    }
    return {
        tokens_in: prev.tokens_in + (usage.input ?? 0),
        tokens_out: prev.tokens_out + (usage.output ?? 0),
        cache_read: prev.cache_read + (usage.cacheRead ?? 0),
        cache_write: prev.cache_write + (usage.cacheWrite ?? 0),
        cost_input: prev.cost_input,
        cost_output: prev.cost_output,
        cost_cache_read: prev.cost_cache_read,
        cost_cache_write: prev.cost_cache_write,
        cost_total: prev.cost_total,
    }
}
