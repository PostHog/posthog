import { LLMSentimentMessage, LLMSentimentResult } from '~/queries/schema/schema-general'

export type MessageSentiment = LLMSentimentMessage
export type GenerationSentiment = LLMSentimentResult

export const GENERATION_SENTIMENT_SELECT = "'' -- Sentiment"

const SENTIMENT_LABELS = new Set(['positive', 'neutral', 'negative'])

export function normalizeSentimentResult(value: unknown): GenerationSentiment | null {
    if (!value || typeof value !== 'object') {
        return null
    }

    const raw = value as Record<string, unknown>
    const scores = normalizeScores(raw.scores)
    const label = normalizeLabel(raw.label)
    const score = normalizeNumber(raw.score) ?? scores[label] ?? 0
    const messages = normalizeMessages(raw.messages)

    return {
        label,
        score,
        scores,
        messages,
        message_count: normalizeInteger(raw.message_count) ?? Object.keys(messages).length,
    }
}

function normalizeJsonish(value: unknown): unknown {
    if (typeof value !== 'string') {
        return value
    }
    if (!value) {
        return null
    }
    try {
        return JSON.parse(value)
    } catch {
        return value
    }
}

function normalizeLabel(value: unknown): string {
    return typeof value === 'string' && SENTIMENT_LABELS.has(value) ? value : 'neutral'
}

function normalizeNumber(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return value
    }
    if (typeof value === 'string') {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : null
    }
    return null
}

function normalizeInteger(value: unknown): number | null {
    const parsed = normalizeNumber(value)
    return parsed === null ? null : Math.trunc(parsed)
}

function normalizeScores(value: unknown): Record<string, number> {
    const decoded = normalizeJsonish(value)
    if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded)) {
        return { positive: 0, neutral: 0, negative: 0 }
    }

    const raw = decoded as Record<string, unknown>
    return {
        positive: normalizeNumber(raw.positive) ?? 0,
        neutral: normalizeNumber(raw.neutral) ?? 0,
        negative: normalizeNumber(raw.negative) ?? 0,
    }
}

function normalizeMessages(value: unknown): Record<string, MessageSentiment> {
    const decoded = normalizeJsonish(value)
    if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded)) {
        return {}
    }

    const messages: Record<string, MessageSentiment> = {}
    for (const [key, rawMessage] of Object.entries(decoded as Record<string, unknown>)) {
        if (!rawMessage || typeof rawMessage !== 'object' || Array.isArray(rawMessage)) {
            continue
        }

        const message = rawMessage as Record<string, unknown>
        messages[key] = {
            label: normalizeLabel(message.label),
            score: normalizeNumber(message.score) ?? 0,
            scores: normalizeScores(message.scores),
        }
    }

    return messages
}
