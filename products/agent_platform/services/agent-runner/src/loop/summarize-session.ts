/**
 * One-shot LLM summary of a finished session. Runs at the terminal transition
 * (worker) and from the backfill script. Feeds the cheap, envelope-stripped
 * `buildSearchText` digest to the model via pi-ai's non-streaming
 * `completeSimple`, then parses the strict JSON reply. Best-effort: returns
 * null (caller leaves the row unsummarized to retry) rather than throwing.
 */

import { type Api, completeSimple, type Model } from '@earendil-works/pi-ai'

import {
    buildSearchText,
    buildSummaryUserPrompt,
    type ConversationMessage,
    parseSummaryResponse,
    type SessionSummaryResult,
    SUMMARY_SYSTEM_PROMPT,
} from '@posthog/agent-shared'

/** The reply is 1–2 sentences + two short labels — a tight ceiling is plenty. */
const SUMMARY_MAX_TOKENS = 300

export async function generateSessionSummary(
    model: Model<string>,
    conversation: ConversationMessage[],
    opts: { apiKey?: string; signal?: AbortSignal } = {}
): Promise<SessionSummaryResult | null> {
    const digest = buildSearchText(conversation)
    if (!digest) {
        return null
    }
    const reply = await completeSimple(
        model as Model<Api>,
        {
            systemPrompt: SUMMARY_SYSTEM_PROMPT,
            messages: [{ role: 'user', content: buildSummaryUserPrompt(digest), timestamp: Date.now() }],
        },
        { apiKey: opts.apiKey, maxTokens: SUMMARY_MAX_TOKENS, signal: opts.signal }
    )
    const text = reply.content
        .filter((c): c is { type: 'text'; text: string } => c.type === 'text')
        .map((c) => c.text)
        .join('')
    return parseSummaryResponse(text)
}
