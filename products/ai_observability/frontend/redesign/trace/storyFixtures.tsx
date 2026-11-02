import type { Decorator } from '@storybook/react'

import type {
    TraceFeedbackScoreApi,
    TraceNodeApi,
    TraceNodeStatsApi,
    TraceSummaryContentApi,
    TraceTimelineRowApi,
} from '../../generated/api.schemas'
import type { ClusterChipItem, TraceClustersChipProps } from './components/TraceClustersChip'
import { SampleNodeDetail, SampleTraceFixture } from './sampleFixtures/sampleTraceFixture'
import {
    ConversationTurn,
    EvalResult,
    EvalRollupOutcome,
    EvalsChipData,
    FeedbackModeState,
    MessagePart,
    NodeProperties,
    StepFeedback,
    ThreadMessage,
} from './types'

export const FIXTURE_STATS: TraceNodeStatsApi = {
    costUsd: 0.0021,
    inputTokens: 1840,
    outputTokens: 212,
    cacheReadTokens: 1024,
    cacheWriteTokens: 312,
    latencyMs: 2310,
}

const noStats: TraceNodeStatsApi = {
    costUsd: null,
    inputTokens: null,
    outputTokens: null,
    cacheReadTokens: null,
    cacheWriteTokens: null,
    latencyMs: null,
}

export const FIXTURE_TREE: TraceNodeApi[] = [
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
                    cacheWriteTokens: 312,
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

export const FIXTURE_TIMELINE_ROWS: TraceTimelineRowApi[] = [
    {
        id: 'trace-1',
        kind: 'trace',
        name: 'answer-billing-question',
        depth: 0,
        startMs: 0,
        durationMs: 2310,
        hasError: false,
    },
    {
        id: 'span-retrieve',
        kind: 'span',
        name: 'retrieve-context',
        depth: 1,
        startMs: 10,
        durationMs: 410,
        hasError: false,
    },
    {
        id: 'embed-question',
        kind: 'embedding',
        name: 'embed-question',
        depth: 2,
        startMs: 20,
        durationMs: 120,
        hasError: false,
    },
    {
        id: 'span-search',
        kind: 'span',
        name: 'search-help-center',
        depth: 2,
        startMs: 150,
        durationMs: 260,
        hasError: false,
    },
    {
        id: 'gen-answer',
        kind: 'generation',
        name: 'draft-answer',
        depth: 1,
        startMs: 430,
        durationMs: 1880,
        hasError: false,
    },
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

const EVAL_TIMESTAMP = '2026-09-01T10:16:40Z'

export const FIXTURE_EVALS: EvalResult[] = [
    {
        id: 'e-answers',
        name: 'Answers the question',
        href: '/evaluations/answers-the-question',
        outcome: 'pass',
        label: 'True',
        reasoning: 'Explains the seat change directly.',
        timestamp: EVAL_TIMESTAMP,
        isBackfill: false,
        target: null,
    },
    {
        id: 'e-grounded',
        name: 'Grounded in articles',
        href: '/evaluations/grounded-in-articles',
        outcome: 'fail',
        label: 'False',
        reasoning: 'Mentions a date not present in the context.',
        timestamp: EVAL_TIMESTAMP,
        isBackfill: false,
        target: null,
    },
    {
        id: 'e-competitor',
        name: 'Mentions a competitor',
        href: '/evaluations/mentions-a-competitor',
        outcome: 'pass',
        label: 'False',
        reasoning: 'No other product is named.',
        timestamp: EVAL_TIMESTAMP,
        isBackfill: true,
        target: null,
    },
    {
        id: 'e-helpfulness',
        name: 'Helpfulness',
        href: '/evaluations/helpfulness',
        outcome: 'unrated',
        label: '0.82',
        reasoning: 'Clear and specific, but does not say how to reduce seats.',
        timestamp: EVAL_TIMESTAMP,
        isBackfill: false,
        target: null,
    },
    {
        id: 'e-sentiment',
        name: 'User sentiment',
        href: null,
        outcome: 'pass',
        label: 'Positive',
        reasoning: null,
        timestamp: EVAL_TIMESTAMP,
        isBackfill: false,
        target: null,
    },
    {
        id: 'e-refund',
        name: 'Refund policy',
        href: '/evaluations/refund-policy',
        outcome: 'inconclusive',
        label: 'Skipped',
        reasoning: 'The question is not about refunds.',
        timestamp: EVAL_TIMESTAMP,
        isBackfill: false,
        target: null,
    },
]

/** The roll-up of `FIXTURE_EVALS`: three passes, one fail, and the unrated and skipped runs. */
export const FIXTURE_EVALS_CHIP: EvalsChipData = { passed: 3, graded: 4, unrated: 2 }

export const FIXTURE_EVAL_OUTCOMES: Record<string, EvalRollupOutcome> = { 'gen-answer': 'fail' }

export const FIXTURE_TRACE_EVALS: EvalResult[] = FIXTURE_EVALS.map((result) => ({
    ...result,
    target: { label: 'draft-answer', nodeId: 'gen-answer' },
}))

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
        backLink: { label: 'Back to traces', href: '/traces' },
        exportAction: { loading: false, onExport: () => {} },
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
        'trace-1': { ...FIXTURE_SPAN_DETAIL, evals: { status: 'ready', results: FIXTURE_TRACE_EVALS } },
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
    thread: { status: 'ready', turns: [FIXTURE_TURN], activeTurnId: FIXTURE_TURN.id },
    timeline: { rows: FIXTURE_TIMELINE_ROWS, totalMs: 2310 },
}

const feedbackScore = (id: string, name: string | null, value: string, minute: number): TraceFeedbackScoreApi => ({
    id,
    name,
    value,
    nodeId: 'gen-answer',
    timestamp: `2026-09-01T10:${minute}:00Z`,
})

export const FIXTURE_STEP_FEEDBACK: StepFeedback = {
    scores: [
        feedbackScore('score-helpful', 'helpfulness', '0', 16),
        feedbackScore('score-resolved', 'resolved', 'false', 17),
        feedbackScore('score-tone', 'tone', '4.5', 18),
        feedbackScore('score-latency', 'latency_ok', 'true', 19),
        feedbackScore('score-unnamed', null, '{"stars":3}', 20),
    ],
    responseCount: 1,
}

const answerStep = { id: 'gen-answer', name: 'draft-answer' }

export const FIXTURE_FEEDBACK_MODE: Extract<FeedbackModeState, { status: 'ready' }> = {
    status: 'ready',
    scores: [
        { ...feedbackScore('score-helpful', 'helpfulness', '0', 16), step: answerStep, focused: true },
        { ...feedbackScore('score-resolved', 'resolved', 'false', 17), step: answerStep, focused: true },
        { ...feedbackScore('score-csat', 'csat', '4', 21), nodeId: 'trace-1', step: null, focused: false },
        { ...feedbackScore('score-unnamed', null, '{"stars":3}', 22), nodeId: 'trace-1', step: null, focused: false },
    ],
    responses: [
        {
            kind: 'text',
            id: 'text-long',
            text: 'Too long, but correct.',
            nodeId: 'trace-1',
            timestamp: '2026-09-01T10:23:00Z',
            step: null,
            focused: false,
        },
        {
            kind: 'text',
            id: 'text-step',
            text: 'The second paragraph repeats the first one. Shorter answers would help when I am on my phone.',
            nodeId: 'gen-answer',
            timestamp: '2026-09-01T10:24:00Z',
            step: answerStep,
            focused: true,
        },
    ],
    unanswered: [],
    surveysFailed: false,
}

const answerQuality = { id: '0192f2a4-5c1e-7000-8000-00000000a001', name: 'Answer quality' }

export const FIXTURE_FEEDBACK_MODE_WITH_SURVEYS: Extract<FeedbackModeState, { status: 'ready' }> = {
    status: 'ready',
    scores: FIXTURE_FEEDBACK_MODE.scores.map((row) => ({ ...row, focused: false })),
    responses: [
        { ...FIXTURE_FEEDBACK_MODE.responses[0], focused: false },
        {
            kind: 'survey',
            id: 'submission-full',
            nodeId: 'trace-1',
            timestamp: '2026-09-01T10:25:00Z',
            survey: answerQuality,
            answers: [
                { kind: 'thumbs', question: 'Was this answer useful?', up: true },
                {
                    kind: 'rating',
                    question: 'How good was it?',
                    value: '4',
                    scale: 5,
                    lowerLabel: 'Bad',
                    upperLabel: 'Great',
                },
                { kind: 'choice', question: 'What could be better?', choices: ['Accuracy', 'Tone'] },
                { kind: 'text', question: 'Anything else?', text: 'Shorter answers, please.' },
            ],
            complete: true,
            unavailable: null,
            step: null,
            focused: false,
        },
        {
            kind: 'survey',
            id: 'submission-partial',
            nodeId: 'trace-1',
            timestamp: '2026-09-01T10:26:00Z',
            survey: answerQuality,
            answers: [{ kind: 'thumbs', question: 'Was this answer useful?', up: false }],
            complete: false,
            unavailable: null,
            step: null,
            focused: false,
        },
        {
            kind: 'survey',
            id: 'submission-deleted',
            nodeId: 'trace-1',
            timestamp: '2026-09-01T10:27:00Z',
            survey: { id: '0192f2a4-5c1e-7000-8000-00000000a002', name: null },
            answers: [],
            complete: true,
            unavailable: 'survey_not_found',
            step: null,
            focused: false,
        },
        {
            kind: 'survey',
            id: 'submission-empty',
            nodeId: 'trace-1',
            timestamp: '2026-09-01T10:28:00Z',
            survey: { id: '0192f2a4-5c1e-7000-8000-00000000a003', name: 'Draft survey' },
            answers: [],
            complete: true,
            unavailable: 'no_questions',
            step: null,
            focused: false,
        },
    ],
    unanswered: [
        {
            survey: { id: '0192f2a4-5c1e-7000-8000-00000000a004', name: 'Follow-up' },
            timestamp: '2026-09-01T10:29:00Z',
        },
        { survey: { id: '0192f2a4-5c1e-7000-8000-00000000a005', name: null }, timestamp: '2026-09-01T10:30:00Z' },
    ],
    surveysFailed: false,
}

export const FIXTURE_SUMMARY: TraceSummaryContentApi = {
    title: 'Billing question answered from invoice history',
    bullets: [
        { text: 'The user asks why their latest invoice is higher than the one before.', nodeId: 'gen-answer' },
        { text: 'The agent searches the billing records for seat changes in the period.', nodeId: 'span-search' },
        {
            text: 'Two seats were added mid-cycle, and the prorated charge for them explains the whole difference between the two invoices.',
            nodeId: 'gen-answer',
        },
        { text: 'The answer cites the seat change dates.', nodeId: null },
    ],
    notes: [
        { text: 'The retrieval step returned three documents but the answer uses only one.', nodeId: 'span-retrieve' },
    ],
    flow: 'question → retrieve-context → search-billing → answer\n                      └─→ 3 documents found ✓',
    model: 'gpt-4.1-mini',
    generatedAt: '2026-09-01T10:20:00Z',
}

export function withWidth(px: number): Decorator {
    return (Story) => (
        <div className="border border-dashed border-primary" style={{ width: px }}>
            <Story />
        </div>
    )
}

export const FIXTURE_CLUSTER: ClusterChipItem = {
    label: 'Billing questions',
    description: 'Users ask why an invoice changed after adding seats.',
    jobName: 'Support conversations',
    isOutlier: false,
    runAt: '2026-09-02T03:40:00Z',
    href: '/ai-observability/clusters/1_trace_20260902_030000/3',
}

export const FIXTURE_OUTLIER_CLUSTER: ClusterChipItem = {
    label: 'Outliers',
    description: null,
    jobName: 'Agent runs',
    isOutlier: true,
    runAt: '2026-09-01T03:40:00Z',
    href: '/ai-observability/clusters/1_trace_20260901_030000/-1',
}

export const FIXTURE_CLUSTERS_CHIP: TraceClustersChipProps = {
    first: FIXTURE_CLUSTER,
    others: [
        FIXTURE_OUTLIER_CLUSTER,
        {
            label: 'Refund requests',
            description: 'Users ask for money back on an annual plan.',
            jobName: null,
            isOutlier: false,
            runAt: '2026-09-02T04:40:00Z',
            href: '/ai-observability/clusters/1_trace_20260902_040000/5',
        },
    ],
}
