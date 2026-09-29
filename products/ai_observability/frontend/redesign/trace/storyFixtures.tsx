import type { Decorator } from '@storybook/react'

import { SampleNodeDetail, SampleTraceFixture } from './sampleFixtures/sampleTraceFixture'
import {
    ConversationTurn,
    EvalResult,
    MessagePart,
    NodeProperties,
    NodeStats,
    ThreadMessage,
    TimelineRowData,
    TraceTreeNode,
} from './types'

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

export const FIXTURE_GENERATION_PROPERTIES: NodeProperties = {
    timestamp: '2026-09-01T10:15:02Z',
    provider: 'openai',
    temperature: 0.2,
    sessionId: 'sess-7f3a',
    promptName: 'billing-answer',
    promptVersion: 6,
    person: 'ana@example.com',
}

export const FIXTURE_SPAN_PROPERTIES: NodeProperties = {
    timestamp: '2026-09-01T10:15:00Z',
    provider: null,
    temperature: null,
    sessionId: 'sess-7f3a',
    promptName: null,
    promptVersion: null,
    person: 'ana@example.com',
}

export const FIXTURE_GENERATION_INPUT: ThreadMessage[] = [
    {
        id: 'm-system',
        role: 'system',
        parts: [
            {
                kind: 'text',
                text: 'You answer billing questions for Hedgebox.\n\n## Rules\n- Use only the provided articles.\n- Keep answers **short**.',
            },
        ],
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
]

export const FIXTURE_GENERATION_OUTPUT: ThreadMessage[] = [
    {
        id: 'm-answer',
        role: 'assistant',
        parts: [
            {
                kind: 'text',
                text: 'Your team went from **4 to 6 seats** on August 12, so the invoice includes two extra seats for the rest of the month.',
            },
        ],
        isInternal: false,
        sourceNodeId: 'gen-answer',
    },
]

export const FIXTURE_GENERATION_MESSAGES: ThreadMessage[] = [...FIXTURE_GENERATION_INPUT, ...FIXTURE_GENERATION_OUTPUT]

export const FIXTURE_TURN: ConversationTurn = {
    id: 'trace-1',
    timestamp: '2026-09-01T10:15:00Z',
    messages: FIXTURE_GENERATION_MESSAGES,
    error: null,
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

const INLINE_CHART_SVG =
    "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='96'><rect width='160' height='96' fill='lavender'/><rect x='16' y='56' width='24' height='28' fill='slateblue'/><rect x='56' y='36' width='24' height='48' fill='slateblue'/><rect x='96' y='16' width='24' height='68' fill='slateblue'/></svg>"

export const FIXTURE_ATTACHMENT_EXTERNAL_AUDIO: MessagePart = {
    kind: 'attachment',
    mediaType: 'audio',
    name: null,
    mimeType: 'audio/wav',
    url: 'https://media.example.com/voice-note.wav',
}

export const FIXTURE_ATTACHMENT_SAME_ORIGIN_AUDIO: MessagePart = {
    kind: 'attachment',
    mediaType: 'audio',
    name: 'clip.wav',
    mimeType: 'audio/wav',
    url: '/api/projects/1/ai_blob/v1/sha256/4f6e9c2a1b3d5e7f8091a2b3c4d5e6f7089a1b2c3d4e5f60718293a4b5c6d7e',
}

export const FIXTURE_ATTACHMENT_REJECTED_IMAGE_URL: MessagePart = {
    kind: 'attachment',
    mediaType: 'image',
    name: 'suspicious-chart.png',
    mimeType: 'image/png',
    url: '//evil.example.com/x',
}

export const FIXTURE_ATTACHMENT_DATA_FILE: MessagePart = {
    kind: 'attachment',
    mediaType: 'file',
    name: 'notes.txt',
    mimeType: 'text/plain',
    url: 'data:text/plain;base64,SGVsbG8gZnJvbSBQb3N0SG9nIQ==',
}

export const FIXTURE_ATTACHMENT_PARTS: MessagePart[] = [
    {
        kind: 'attachment',
        mediaType: 'image',
        name: 'seat-usage.svg',
        mimeType: 'image/svg+xml',
        url: `data:image/svg+xml,${encodeURIComponent(INLINE_CHART_SVG)}`,
    },
    FIXTURE_ATTACHMENT_EXTERNAL_AUDIO,
    {
        kind: 'attachment',
        mediaType: 'video',
        name: 'screen-recording.mp4',
        mimeType: 'video/mp4',
        url: 'https://media.example.com/screen-recording.mp4',
    },
    {
        kind: 'attachment',
        mediaType: 'file',
        name: 'invoice-august.pdf',
        mimeType: 'application/pdf',
        url: 'https://media.example.com/invoice-august.pdf',
    },
    { kind: 'attachment', mediaType: 'file', name: null, mimeType: 'text/csv', url: null },
    FIXTURE_ATTACHMENT_SAME_ORIGIN_AUDIO,
    FIXTURE_ATTACHMENT_DATA_FILE,
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

const FIXTURE_SPAN_DETAIL: SampleNodeDetail = {
    content: { kind: 'io', input: { question: 'Why did my invoice go up?' }, output: { hits: 3 } },
    error: null,
    properties: FIXTURE_SPAN_PROPERTIES,
    evals: { status: 'ready', results: [] },
    raw: { event: '$ai_span' },
}

export const FIXTURE_TRACE: SampleTraceFixture = {
    header: {
        name: 'answer-billing-question',
        hasError: false,
        olderHref: '/older',
        newerHref: '/newer',
        backHref: '/traces',
    },
    summary: {
        traceId: '3f9c2a71-5b8e-4d0f-a1c2-7e6d5b4a3c21',
        timestamp: '2026-09-01T10:15:00Z',
        person: { label: 'ana@example.com', href: '/person/ana' },
        totals: FIXTURE_STATS,
    },
    tree: FIXTURE_TREE,
    initialNodeId: 'gen-answer',
    details: {
        'trace-1': FIXTURE_SPAN_DETAIL,
        'span-retrieve': FIXTURE_SPAN_DETAIL,
        'embed-question': FIXTURE_SPAN_DETAIL,
        'span-search': FIXTURE_SPAN_DETAIL,
        'gen-answer': {
            content: { kind: 'messages', input: FIXTURE_GENERATION_INPUT, output: FIXTURE_GENERATION_OUTPUT },
            error: null,
            properties: FIXTURE_GENERATION_PROPERTIES,
            evals: { status: 'ready', results: FIXTURE_EVALS },
            raw: { event: '$ai_generation', id: 'gen-answer' },
        },
    },
    thread: { turns: [FIXTURE_TURN], activeTurnId: FIXTURE_TURN.id },
    timeline: { rows: FIXTURE_TIMELINE_ROWS, totalMs: 2310 },
}

export function withWidth(px: number): Decorator {
    return (Story) => (
        <div className="border border-dashed border-primary" style={{ width: px }}>
            <Story />
        </div>
    )
}
