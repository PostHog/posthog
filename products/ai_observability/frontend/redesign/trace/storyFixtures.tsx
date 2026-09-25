import type { Decorator } from '@storybook/react'

import { ConversationTurn, EvalResult, NodeStats, ThreadMessage, TimelineRowData, TraceTreeNode } from './types'

export const FIXTURE_STATS: NodeStats = {
    costUsd: 0.0021,
    inputTokens: 1840,
    outputTokens: 212,
    cacheReadTokens: 1024,
    latencyMs: 2310,
}

const noStats: NodeStats = {
    costUsd: null,
    inputTokens: null,
    outputTokens: null,
    cacheReadTokens: null,
    latencyMs: null,
}

export const FIXTURE_TREE: TraceTreeNode[] = [
    {
        id: 'trace-1',
        kind: 'trace',
        name: 'answer-billing-question',
        model: null,
        stats: FIXTURE_STATS,
        hasError: false,
        children: [
            {
                id: 'span-retrieve',
                kind: 'span',
                name: 'retrieve-context',
                model: null,
                stats: { ...noStats, latencyMs: 410 },
                hasError: false,
                children: [
                    {
                        id: 'embed-question',
                        kind: 'embedding',
                        name: 'embed-question',
                        model: 'text-embedding-3-small',
                        stats: { ...noStats, inputTokens: 18, latencyMs: 120, costUsd: 0 },
                        hasError: false,
                        children: [],
                    },
                    {
                        id: 'span-search',
                        kind: 'span',
                        name: 'search-help-center',
                        model: null,
                        stats: { ...noStats, latencyMs: 260 },
                        hasError: false,
                        children: [],
                    },
                ],
            },
            {
                id: 'gen-answer',
                kind: 'generation',
                name: 'draft-answer',
                model: 'gpt-4.1-mini',
                stats: {
                    costUsd: 0.0021,
                    inputTokens: 1822,
                    outputTokens: 212,
                    cacheReadTokens: 1024,
                    latencyMs: 1880,
                },
                hasError: false,
                children: [],
            },
        ],
    },
]

export const FIXTURE_GENERATION_MESSAGES: ThreadMessage[] = [
    {
        id: 'm-system',
        role: 'system',
        parts: [{ kind: 'text', text: 'You answer billing questions for Hedgebox. Use only the provided articles.' }],
        isInternal: true,
        sourceNodeId: 'gen-answer',
    },
    {
        id: 'm-user',
        role: 'user',
        parts: [{ kind: 'text', text: 'Why did my invoice go up this month?' }],
        isInternal: false,
        sourceNodeId: 'gen-answer',
    },
    {
        id: 'm-tool',
        role: 'assistant',
        parts: [
            {
                kind: 'toolCall',
                name: 'lookup_invoice',
                args: { month: '2026-08' },
                result: { seats: { before: 4, after: 6 }, total_usd: 180 },
            },
        ],
        isInternal: true,
        sourceNodeId: 'gen-answer',
    },
    {
        id: 'm-answer',
        role: 'assistant',
        parts: [
            {
                kind: 'text',
                text: 'Your team went from 4 to 6 seats on August 12, so the invoice includes two extra seats for the rest of the month.',
            },
        ],
        isInternal: false,
        sourceNodeId: 'gen-answer',
    },
]

export const FIXTURE_TURN: ConversationTurn = {
    id: 'trace-1',
    timestamp: '2026-09-01T10:15:00Z',
    messages: FIXTURE_GENERATION_MESSAGES,
}

export const FIXTURE_TIMELINE_ROWS: TimelineRowData[] = [
    { id: 'trace-1', kind: 'trace', name: 'answer-billing-question', depth: 0, startMs: 0, durationMs: 2310 },
    { id: 'span-retrieve', kind: 'span', name: 'retrieve-context', depth: 1, startMs: 10, durationMs: 410 },
    {
        id: 'embed-question',
        kind: 'embedding',
        name: 'embed-question',
        depth: 2,
        startMs: 20,
        durationMs: 120,
    },
    { id: 'span-search', kind: 'span', name: 'search-help-center', depth: 2, startMs: 150, durationMs: 260 },
    { id: 'gen-answer', kind: 'generation', name: 'draft-answer', depth: 1, startMs: 430, durationMs: 1880 },
]

export const FIXTURE_EVALS: EvalResult[] = [
    {
        id: 'e1',
        name: 'Answers the question',
        verdict: 'pass',
        reasoning: 'Explains the seat change directly.',
    },
    {
        id: 'e2',
        name: 'Grounded in articles',
        verdict: 'fail',
        reasoning: 'Mentions a date not present in the context.',
    },
    { id: 'e3', name: 'Refund policy', verdict: 'na', reasoning: null },
]

export function withWidth(px: number): Decorator {
    return (Story) => (
        <div className="border border-dashed border-primary" style={{ width: px }}>
            <Story />
        </div>
    )
}
