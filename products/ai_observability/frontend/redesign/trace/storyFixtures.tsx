import type { Decorator } from '@storybook/react'

import type {
    TraceClusterApi,
    TraceEvaluationResultApi,
    TraceFeedbackApi,
    TraceEvaluationSummaryApi,
    TraceFeedbackScoreApi,
    TraceNodeApi,
    TraceNodeContentApi,
    TraceNodeStatsApi,
    TraceStepFeedbackApi,
    TraceSummaryContentApi,
    TraceTimelineRowApi,
} from '../../generated/api.schemas'
import type { TraceSummaryBarProps } from './components/TraceSummaryBar'
import { jsonContent, messagesContent, messagesSides } from './sampleFixtures/sampleContent'
import { SampleNodeDetail, SampleTraceFixture, sampleDetail, sampleRaw } from './sampleFixtures/sampleTraceFixture'
import { ConversationTurn, EvalRollupOutcome, FeedbackStepContext, MessagePart, ThreadMessage } from './types'

export const FIXTURE_STATS: TraceNodeStatsApi = {
    costUsd: 0.0021,
    inputTokens: 1840,
    outputTokens: 212,
    cacheReadTokens: 1024,
    cacheWriteTokens: 312,
    latencyMs: 2310,
}

export const FIXTURE_SUMMARY_TRACE: TraceSummaryBarProps['trace'] = {
    id: '3f9c2a71-5b8e-4d0f-a1c2-7e6d5b4a3c21',
    createdAt: '2026-09-01T10:15:00Z',
    person: { distinctId: 'ana', label: 'ana@example.com' },
    totals: FIXTURE_STATS,
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
        label: 'answer-billing-question',
        model: null,
        stats: FIXTURE_STATS,
        hasError: false,
        children: [
            {
                id: 'span-retrieve',
                kind: 'span',
                name: 'retrieve-context',
                label: 'retrieve-context',
                model: null,
                stats: { ...noStats, latencyMs: 410 },
                hasError: false,
                children: [
                    {
                        id: 'embed-question',
                        kind: 'embedding',
                        name: 'embed-question',
                        label: 'embed-question',
                        model: 'text-embedding-3-small',
                        stats: { ...noStats, inputTokens: 18, latencyMs: 120, costUsd: 0 },
                        hasError: false,
                        children: [],
                    },
                    {
                        id: 'span-search',
                        kind: 'span',
                        name: 'search-help-center',
                        label: 'search-help-center',
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
                label: 'draft-answer',
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

const FIXTURE_SESSION_ID = 'sess-7f3a'

/** The `draft-answer` generation read with the given content. */
export function fixtureGenerationDetail(content: TraceNodeContentApi, error: string | null = null): SampleNodeDetail {
    return sampleDetail({
        content,
        error,
        metadata: {
            provider: 'openai',
            temperature: 0.2,
            sessionId: FIXTURE_SESSION_ID,
            promptName: 'billing-answer',
            promptVersion: 6,
        },
        raw: sampleRaw('generation', 'gen-answer', {
            name: '$ai_generation',
            timestamp: '2026-09-01T10:15:02Z',
            properties: {},
        }),
    })
}

/** A span read with the given content. */
export function fixtureSpanDetail(content: TraceNodeContentApi): SampleNodeDetail {
    return sampleDetail({
        content,
        metadata: { sessionId: FIXTURE_SESSION_ID },
        raw: sampleRaw('span', 'span-1', { name: '$ai_span', timestamp: '2026-09-01T10:15:00Z', properties: {} }),
    })
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

const AGENT_TURNS: { ask: string; tool: string; args: Record<string, unknown>; result: string; answer: string }[] = [
    {
        ask: 'Which plan are we on?',
        tool: 'get_subscription',
        args: { team: 'hedgebox' },
        result: '{"plan": "Team", "seats": 6, "renews": "2026-09-30"}',
        answer: 'You are on the **Team** plan with 6 seats, renewing on September 30.',
    },
    {
        ask: 'How many seats did we use last month?',
        tool: 'seat_usage',
        args: { month: '2026-08' },
        result: '{"peak": 6, "average": 5.2}',
        answer: 'Usage peaked at 6 seats in August, with an average of 5.2.',
    },
    {
        ask: 'Can we drop back to 4 seats?',
        tool: 'seat_change_preview',
        args: { seats: 4 },
        result: '{"allowed": true, "effective": "2026-09-30", "saving_usd": 60}',
        answer: 'Yes. The change takes effect on September 30 and saves $60 a month.',
    },
    {
        ask: 'Do it, and email me the new invoice.',
        tool: 'change_seats',
        args: { seats: 4, notify: 'ana@example.com' },
        result: '{"status": "scheduled", "effective": "2026-09-30"}',
        answer: '',
    },
]

function agentMessage(id: string, role: ThreadMessage['role'], parts: ThreadMessage['parts']): ThreadMessage {
    return { id, role, parts, isInternal: role !== 'user', sourceNodeId: 'gen-answer' }
}

/** An agent step whose input holds four user turns, each with a tool call, so the earlier turns can collapse. */
export const FIXTURE_LONG_AGENT_INPUT: ThreadMessage[] = [
    FIXTURE_GENERATION_INPUT[0],
    ...AGENT_TURNS.flatMap((turn, index) => [
        agentMessage(`agent-${index}-user`, 'user', [{ kind: 'text', text: turn.ask }]),
        agentMessage(`agent-${index}-call`, 'assistant', [
            { kind: 'toolCall', name: turn.tool, args: turn.args, result: null },
        ]),
        agentMessage(`agent-${index}-result`, 'tool', [{ kind: 'text', text: turn.result }]),
        ...(turn.answer
            ? [agentMessage(`agent-${index}-answer`, 'assistant', [{ kind: 'text', text: turn.answer }])]
            : []),
    ]),
]

export const FIXTURE_LONG_AGENT_OUTPUT: ThreadMessage[] = [
    agentMessage('agent-final', 'assistant', [
        {
            kind: 'text',
            text: 'Done. Your team drops to **4 seats** on September 30, and the new invoice is on its way to ana@example.com.',
        },
    ]),
]

const SEAT_HISTORY = Array.from({ length: 24 }, (_, index) => ({
    month: `2026-${String((index % 12) + 1).padStart(2, '0')}`,
    seats: 4 + (index % 3),
    note: 'Seat count from the billing snapshot taken on the first day of the month, before any proration.',
}))

/** An answer taller than any window: a preamble, a long report and a tool call with a long JSON result. */
export const FIXTURE_LONG_ANSWER_MESSAGE: ThreadMessage = agentMessage('long-answer', 'assistant', [
    {
        kind: 'text',
        text: [
            'You are a billing assistant. Answer in markdown, cite the invoice month, and never share card details.',
            '',
            '## Seat history',
            '',
            ...SEAT_HISTORY.map(({ month, seats }) => `- **${month}:** ${seats} seats, billed at the team plan rate.`),
            '',
            '## What changed',
            '',
            ...SEAT_HISTORY.map(({ month }) => `1. ${month}: the invoice shows one prorated line for the seat change.`),
            '',
            'The seat count changed at most once a month, so every invoice line matches one row above.',
        ].join('\n'),
    },
    {
        kind: 'toolCall',
        name: 'lookup_seat_history',
        args: { team: 'team-42', months: 24 },
        result: { team: 'team-42', history: SEAT_HISTORY },
    },
])

export const FIXTURE_TURN: ConversationTurn = {
    id: 'trace-1',
    timestamp: '2026-09-01T10:15:00Z',
    ...messagesSides(FIXTURE_GENERATION_INPUT, FIXTURE_GENERATION_OUTPUT),
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

function fixtureEval(
    result: Pick<
        TraceEvaluationResultApi,
        'id' | 'evaluationId' | 'evaluationName' | 'outcome' | 'label' | 'reasoning' | 'isBackfill'
    >
): TraceEvaluationResultApi {
    return { ...result, targetNodeId: 'gen-answer', score: null, timestamp: EVAL_TIMESTAMP }
}

/** Every result targets the `draft-answer` generation. */
export const FIXTURE_EVALS: TraceEvaluationResultApi[] = [
    fixtureEval({
        id: 'e-answers',
        evaluationId: 'answers-the-question',
        evaluationName: 'Answers the question',
        outcome: 'pass',
        label: 'True',
        reasoning: 'Explains the seat change directly.',
        isBackfill: false,
    }),
    fixtureEval({
        id: 'e-grounded',
        evaluationId: 'grounded-in-articles',
        evaluationName: 'Grounded in articles',
        outcome: 'fail',
        label: 'False',
        reasoning: 'Mentions a date not present in the context.',
        isBackfill: false,
    }),
    fixtureEval({
        id: 'e-competitor',
        evaluationId: 'mentions-a-competitor',
        evaluationName: 'Mentions a competitor',
        outcome: 'pass',
        label: 'False',
        reasoning: 'No other product is named.',
        isBackfill: true,
    }),
    fixtureEval({
        id: 'e-helpfulness',
        evaluationId: 'helpfulness',
        evaluationName: 'Helpfulness',
        outcome: 'unrated',
        label: '0.82',
        reasoning: 'Clear and specific, but does not say how to reduce seats.',
        isBackfill: false,
    }),
    fixtureEval({
        id: 'e-sentiment',
        evaluationId: null,
        evaluationName: 'User sentiment',
        outcome: 'pass',
        label: 'Positive',
        reasoning: null,
        isBackfill: false,
    }),
    fixtureEval({
        id: 'e-refund',
        evaluationId: 'refund-policy',
        evaluationName: 'Refund policy',
        outcome: 'inconclusive',
        label: 'Skipped',
        reasoning: 'The question is not about refunds.',
        isBackfill: false,
    }),
]

/** The roll-up of `FIXTURE_EVALS`: three passes, one fail, and the unrated and skipped runs. */
export const FIXTURE_EVALS_SUMMARY: TraceEvaluationSummaryApi = { passed: 3, failed: 1, unrated: 2, nodes: [] }

export const FIXTURE_EVAL_OUTCOMES: Record<string, EvalRollupOutcome> = { 'gen-answer': 'fail' }

/** Step feedback that only carries counts, for stories that show the tree's feedback markers. */
export function stepFeedbackWithCounts(counts: Record<string, number>): ReadonlyMap<string, TraceStepFeedbackApi> {
    return new Map(
        Object.entries(counts).map(([nodeId, total]) => [nodeId, { nodeId, scores: [], responseCount: total, total }])
    )
}

const FIXTURE_SPAN_DETAIL = fixtureSpanDetail(jsonContent({ question: 'Why did my invoice go up?' }, { hits: 3 }))

export const FIXTURE_TRACE: SampleTraceFixture = {
    header: {
        name: 'answer-billing-question',
        hasError: false,
        backLink: { label: 'Back to traces', href: '/traces' },
        copyAction: { loading: false, onCopy: () => {} },
        exportAction: { loading: false, onExport: () => {} },
    },
    trace: { ...FIXTURE_SUMMARY_TRACE, sessionId: FIXTURE_SESSION_ID },
    tree: FIXTURE_TREE,
    initialNodeId: 'gen-answer',
    details: {
        'trace-1': FIXTURE_SPAN_DETAIL,
        'span-retrieve': FIXTURE_SPAN_DETAIL,
        'embed-question': FIXTURE_SPAN_DETAIL,
        'span-search': FIXTURE_SPAN_DETAIL,
        'gen-answer': fixtureGenerationDetail(messagesContent(FIXTURE_GENERATION_INPUT, FIXTURE_GENERATION_OUTPUT)),
    },
    evaluationResults: FIXTURE_EVALS,
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

export const FIXTURE_STEP_FEEDBACK: TraceStepFeedbackApi = {
    nodeId: 'gen-answer',
    scores: [
        feedbackScore('score-helpful', 'helpfulness', '0', 16),
        feedbackScore('score-resolved', 'resolved', 'false', 17),
        feedbackScore('score-tone', 'tone', '4.5', 18),
        feedbackScore('score-latency', 'latency_ok', 'true', 19),
        feedbackScore('score-unnamed', null, '{"stars":3}', 20),
    ],
    responseCount: 1,
    total: 6,
}

export const FIXTURE_FEEDBACK: TraceFeedbackApi = {
    scores: [
        { ...feedbackScore('score-helpful', 'helpfulness', '0', 16) },
        { ...feedbackScore('score-resolved', 'resolved', 'false', 17) },
        { ...feedbackScore('score-csat', 'csat', '4', 21), nodeId: 'trace-1' },
        { ...feedbackScore('score-unnamed', null, '{"stars":3}', 22), nodeId: 'trace-1' },
    ],
    responses: [
        {
            kind: 'text',
            id: 'text-long',
            text: 'Too long, but correct.',
            nodeId: 'trace-1',
            timestamp: '2026-09-01T10:23:00Z',
        },
        {
            kind: 'text',
            id: 'text-step',
            text: 'The second paragraph repeats the first one. Shorter answers would help when I am on my phone.',
            nodeId: 'gen-answer',
            timestamp: '2026-09-01T10:24:00Z',
        },
    ],
    unanswered: [],
    surveyResponsesStatus: 'ok',
    summary: { total: 6, thumbsUp: 0, thumbsDown: 0 },
    steps: [
        { nodeId: 'gen-answer', scores: [], responseCount: 1, total: 3 },
        { nodeId: 'trace-1', scores: [], responseCount: 1, total: 3 },
    ],
}

/** The Feedback mode's step context for `FIXTURE_TREE`, opened from no step. */
export const FIXTURE_FEEDBACK_STEPS: FeedbackStepContext = {
    traceId: 'trace-1',
    stepLabels: new Map([
        ['trace-1', 'answer-billing-question'],
        ['gen-answer', 'draft-answer'],
    ]),
    focusNodeId: null,
}

const answerQuality = { id: '0192f2a4-5c1e-7000-8000-00000000a001', name: 'Answer quality' }

export const FIXTURE_FEEDBACK_WITH_SURVEYS: TraceFeedbackApi = {
    ...FIXTURE_FEEDBACK,
    summary: { total: 9, thumbsUp: 1, thumbsDown: 1 },
    responses: [
        FIXTURE_FEEDBACK.responses[0],
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
        },
    ],
    unanswered: [
        {
            survey: { id: '0192f2a4-5c1e-7000-8000-00000000a004', name: 'Follow-up' },
            timestamp: '2026-09-01T10:29:00Z',
        },
        { survey: { id: '0192f2a4-5c1e-7000-8000-00000000a005', name: null }, timestamp: '2026-09-01T10:30:00Z' },
    ],
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

export const withStepScroller: Decorator = (Story) => (
    <div className="h-120 w-160 overflow-y-auto border border-dashed border-primary">
        <Story />
    </div>
)

export function withWidth(px: number): Decorator {
    return (Story) => (
        <div className="border border-dashed border-primary" style={{ width: px }}>
            <Story />
        </div>
    )
}

export const FIXTURE_CLUSTER: TraceClusterApi = {
    runId: '1_trace_20260902_030000',
    runAt: '2026-09-02T03:40:00Z',
    jobId: null,
    jobName: 'Support conversations',
    clusterId: 3,
    title: 'Billing questions',
    label: 'Billing questions',
    description: 'Users ask why an invoice changed after adding seats.',
    isOutlier: false,
}

export const FIXTURE_OUTLIER_CLUSTER: TraceClusterApi = {
    runId: '1_trace_20260901_030000',
    runAt: '2026-09-01T03:40:00Z',
    jobId: null,
    jobName: 'Agent runs',
    clusterId: -1,
    title: null,
    label: 'Outliers',
    description: null,
    isOutlier: true,
}

export const FIXTURE_CLUSTERS: TraceClusterApi[] = [
    FIXTURE_CLUSTER,
    FIXTURE_OUTLIER_CLUSTER,
    {
        runId: '1_trace_20260902_040000',
        runAt: '2026-09-02T04:40:00Z',
        jobId: null,
        jobName: null,
        clusterId: 5,
        title: 'Refund requests',
        label: 'Refund requests',
        description: 'Users ask for money back on an annual plan.',
        isOutlier: false,
    },
]
