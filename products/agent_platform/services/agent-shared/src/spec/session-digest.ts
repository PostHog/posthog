/**
 * Pure session-digest helpers behind the `agent-applications-listen` MCP tool: a compact,
 * payload-free view of a session — last assistant text + a one-line tool-activity
 * summary + state/usage. Lives beside summarize-conversation.ts (whose
 * `lastAssistantTextPreview` it reuses) so the janitor / MCP read paths can share
 * it; the ingress `/internal/session-digest` route is the only consumer today.
 */

import type { AgentSession, ConversationMessage, ImageContent, SessionUsageTotal, TextContent } from './spec'
import { lastAssistantTextPreview } from './summarize-conversation'

/** Digest text-preview budget — larger than summarize-conversation's PREVIEW_MAX
 *  (120, a list-row length) so the latest assistant text isn't clipped short. */
const DIGEST_TEXT_MAX = 2_000
/** Overall digest budget when the caller omits `max_chars`. */
export const DIGEST_MAX_CHARS_DEFAULT = 4_000
export const TERMINAL_SESSION_STATES = new Set<string>(['completed', 'closed', 'cancelled', 'failed'])

/** Byte size of a tool result's content — never the content itself. */
export function toolResultBytes(content: (TextContent | ImageContent)[]): number {
    let n = 0
    for (const block of content) {
        n += block.type === 'text' ? Buffer.byteLength(block.text, 'utf8') : block.data.length
    }
    return n
}

/**
 * One line summarizing tool activity in a conversation slice: `name ×calls, NB,
 * err×E` per tool, joined by `; `. Walks assistant `toolCall` blocks and
 * top-level `toolResult` messages. Never emits arguments or result payloads.
 */
export function buildToolActivityLine(slice: ConversationMessage[]): string {
    const calls = new Map<string, number>()
    const bytes = new Map<string, number>()
    const errors = new Map<string, number>()
    for (const m of slice) {
        if (m.role === 'assistant') {
            for (const c of m.content) {
                if (c.type === 'toolCall') {
                    calls.set(c.name, (calls.get(c.name) ?? 0) + 1)
                }
            }
        } else if (m.role === 'toolResult') {
            bytes.set(m.toolName, (bytes.get(m.toolName) ?? 0) + toolResultBytes(m.content))
            if (m.isError) {
                errors.set(m.toolName, (errors.get(m.toolName) ?? 0) + 1)
            }
        }
    }
    const names = new Set<string>([...calls.keys(), ...bytes.keys()])
    if (names.size === 0) {
        return ''
    }
    const parts: string[] = []
    for (const name of names) {
        let s = `${name} ×${calls.get(name) ?? 0}`
        const b = bytes.get(name)
        if (b !== undefined) {
            s += `, ${b}B`
        }
        const e = errors.get(name)
        if (e) {
            s += `, err×${e}`
        }
        parts.push(s)
    }
    return parts.join('; ')
}

export function usageLine(u: SessionUsageTotal): string {
    return `tokens_in=${u.tokens_in} tokens_out=${u.tokens_out} cost_total=${u.cost_total}`
}

/**
 * Render the digest for a slice and clip it to `maxChars` (code-point-safe, so
 * surrogate pairs never split — mirrors summarize-conversation's truncation).
 * A clipped digest ends in a pointer telling the caller to re-poll for detail.
 */
export function renderSessionDigest(
    session: AgentSession,
    slice: ConversationMessage[],
    nextCursor: number,
    maxChars: number
): { digest: string; truncated: boolean } {
    // Prefer the new slice's last assistant text; fall back to the whole
    // conversation's last text (the slice may hold only tool traffic or a user turn).
    const text =
        lastAssistantTextPreview(slice, DIGEST_TEXT_MAX) ??
        lastAssistantTextPreview(session.conversation, DIGEST_TEXT_MAX)
    const tools = buildToolActivityLine(slice)
    const lines = [
        text ?? '(no assistant text yet)',
        tools ? `Tools: ${tools}` : 'Tools: (none)',
        `state=${session.state} turns=${session.conversation.length} ${usageLine(session.usage_total)}`,
    ]
    const full = lines.join('\n\n')
    const chars = Array.from(full)
    if (chars.length <= maxChars) {
        return { digest: full, truncated: false }
    }
    const pointer = ` …[digest clipped; re-poll with cursor=${nextCursor}]`
    const budget = Math.max(0, maxChars - Array.from(pointer).length)
    const clipped = chars.slice(0, budget).join('') + pointer
    // Hard cap: when maxChars is smaller than the pointer itself, the cap wins
    // over the pointer so the digest never exceeds the caller's max_chars.
    return { digest: Array.from(clipped).slice(0, maxChars).join(''), truncated: true }
}
