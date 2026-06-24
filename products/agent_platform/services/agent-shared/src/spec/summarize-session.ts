/**
 * LLM session-summary prompt + response parsing. Pure + transport-free: the
 * caller (runner at terminal, or the backfill script) feeds the digest to a
 * model and hands the raw text back here to parse. Keeps the model wiring out
 * of agent-shared while the prompt/shape stay testable in one place.
 */

/** How the session ended, from the model's read of the transcript. */
export type SummaryOutcome = 'resolved' | 'failed' | 'abandoned' | 'other'

export const SUMMARY_OUTCOMES: readonly SummaryOutcome[] = ['resolved', 'failed', 'abandoned', 'other']

export interface SessionSummaryResult {
    /** 1–2 sentence operator-facing summary: what the user wanted + what happened. */
    summary: string
    /** Short 2–4 word topic label for grouping ("model config", "deploy help"). */
    topic: string
    outcome: SummaryOutcome
}

/** Hard caps so a misbehaving model can't bloat the row. */
const SUMMARY_MAX = 600
const TOPIC_MAX = 60

export const SUMMARY_SYSTEM_PROMPT = [
    'You summarize a single AI-agent session for an operator skimming a list of sessions',
    'and for spotting how the agent is being used. You are given a plain-text digest of the',
    'conversation (user + assistant turns).',
    '',
    'Reply with ONLY a minified JSON object, no prose, no code fences:',
    '{"summary": string, "topic": string, "outcome": "resolved"|"failed"|"abandoned"|"other"}',
    '',
    '- summary: 1–2 sentences — what the user wanted and what the agent did / how it ended.',
    '- topic: a 2–4 word lowercase label suitable for grouping sessions by intent.',
    '- outcome: resolved (goal met), failed (errored / could not), abandoned (user dropped off),',
    '  or other.',
    'Write plainly; do not invent details not present in the digest.',
].join('\n')

export function buildSummaryUserPrompt(digest: string): string {
    return `Conversation digest:\n\n${digest}`
}

function clampText(value: unknown, max: number): string {
    if (typeof value !== 'string') {
        return ''
    }
    const collapsed = value.replace(/\s+/g, ' ').trim()
    const chars = Array.from(collapsed)
    return chars.length > max ? chars.slice(0, max).join('') : collapsed
}

function coerceOutcome(value: unknown): SummaryOutcome {
    return typeof value === 'string' && (SUMMARY_OUTCOMES as readonly string[]).includes(value)
        ? (value as SummaryOutcome)
        : 'other'
}

/**
 * Parse the model's reply into a {@link SessionSummaryResult}, tolerating code
 * fences / surrounding prose by extracting the first JSON object. Returns null
 * when no usable summary can be recovered (caller leaves the row unsummarized
 * to retry later) — never throws.
 */
export function parseSummaryResponse(raw: string): SessionSummaryResult | null {
    const match = raw.match(/\{[\s\S]*\}/)
    if (!match) {
        return null
    }
    let parsed: Record<string, unknown>
    try {
        parsed = JSON.parse(match[0]) as Record<string, unknown>
    } catch {
        return null
    }
    const summary = clampText(parsed.summary, SUMMARY_MAX)
    if (!summary) {
        return null
    }
    return {
        summary,
        topic: clampText(parsed.topic, TOPIC_MAX),
        outcome: coerceOutcome(parsed.outcome),
    }
}
