import { urls } from 'scenes/urls'

import { EvaluationOutputConfig, EvaluationRun, LLMJudgeEvaluation } from '../../../evaluations/types'
import { TraceTreeNode } from '../types'
import { EvalResultsContext, toEvalResults } from './toEvalResults'

const node = (
    id: string,
    kind: TraceTreeNode['kind'],
    name: string,
    children: TraceTreeNode[] = []
): TraceTreeNode => ({
    id,
    kind,
    name,
    model: null,
    hasError: false,
    children,
    stats: {
        costUsd: null,
        inputTokens: null,
        outputTokens: null,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        latencyMs: null,
    },
})

const tree = [
    node('trace-1', 'trace', 'answer-billing-question', [
        node('gen-1', 'generation', 'gpt-4.1-mini (openai)'),
        node('span-1', 'span', 'lookup-invoice'),
        node('gen-2', 'generation', 'gpt-4.1-mini (openai)'),
    ]),
]

const run = (overrides: Partial<EvaluationRun> = {}): EvaluationRun => ({
    id: 'r1',
    evaluation_id: 'ev-helpful',
    evaluation_name: 'Answers the question',
    generation_id: null,
    trace_id: 'trace-1',
    timestamp: '2026-09-01T10:16:00Z',
    result: true,
    reasoning: 'Direct answer.',
    status: 'completed',
    ...overrides,
})

const evaluation = (id: string, outputConfig: EvaluationOutputConfig): LLMJudgeEvaluation => ({
    id,
    name: id,
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Grade the answer.' },
    output_type: 'numeric',
    output_config: outputConfig,
    conditions: [],
    target: 'generation',
    target_config: {},
    model_configuration: null,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
})

const context = (overrides: Partial<EvalResultsContext> = {}): EvalResultsContext => ({
    tree,
    viewedNodeId: 'trace-1',
    evaluations: [evaluation('ev-quality', { passing_rule: { operator: 'gte', threshold: 0.7 } })],
    detectorEvaluationIds: ['ev-detector'],
    ...overrides,
})

describe('toEvalResults', () => {
    it.each<[string, Partial<EvaluationRun>, string, string]>([
        ['a failed run', { status: 'failed' }, 'error', 'Error'],
        ['a running run', { status: 'running' }, 'pending', 'Running'],
        ['a true result', { result: true }, 'pass', 'True'],
        ['a false result', { result: false }, 'fail', 'False'],
        ['a true result from a detector', { evaluation_id: 'ev-detector', result: true }, 'fail', 'True'],
        ['a false result from a detector', { evaluation_id: 'ev-detector', result: false }, 'pass', 'False'],
        ['a skipped run, whose result is still false', { skipped: true, result: false }, 'inconclusive', 'Skipped'],
        ['a missing result', { result: null }, 'inconclusive', 'N/A'],
        ['a score with no passing rule', { result_type: 'numeric', score: 0.82 }, 'unrated', '0.82'],
        [
            'a score under the passing threshold',
            { evaluation_id: 'ev-quality', result_type: 'numeric', score: 0.4 },
            'fail',
            '0.4',
        ],
        ['a numeric run with no score', { result_type: 'numeric', score: null }, 'inconclusive', 'No score'],
        ['a positive sentiment', { result_type: 'sentiment', sentiment_label: 'positive' }, 'pass', 'Positive'],
        ['a neutral sentiment', { result_type: 'sentiment', sentiment_label: 'neutral' }, 'unrated', 'Neutral'],
        ['an unknown sentiment', { result_type: 'sentiment', sentiment_label: null }, 'inconclusive', 'Unknown'],
    ])('maps %s to %s', (_name, overrides, outcome, label) => {
        expect(toEvalResults([run(overrides)], context())).toMatchObject([{ outcome, label }])
    })

    it('lists the newest verdict first, dating a backfill by when it ran, and marks backfills', () => {
        const results = toEvalResults(
            [
                run({ id: 'live', timestamp: '2026-09-01T10:16:00Z' }),
                run({
                    id: 'backfill',
                    timestamp: '2026-09-01T10:15:30Z',
                    start_time: '2026-09-20T08:00:00Z',
                    backfill_id: 'backfill-1',
                }),
                run({ id: 'older', timestamp: '2026-09-01T10:15:45Z' }),
            ],
            context()
        )
        expect(results.map((result) => [result.id, result.isBackfill, result.timestamp])).toEqual([
            ['backfill', true, '2026-09-01T10:15:30Z'],
            ['live', false, '2026-09-01T10:16:00Z'],
            ['older', false, '2026-09-01T10:15:45Z'],
        ])
        expect(results[0].href).toBe(urls.aiObservabilityEvaluation('ev-helpful'))
    })

    it.each([
        ['a trace-level run seen on the root targets nothing', 'trace-1', null, null],
        [
            'a run on a generation seen on the root names that generation apart from its namesake',
            'trace-1',
            'gen-2',
            { nodeId: 'gen-2', label: 'gpt-4.1-mini (openai) #2' },
        ],
        ['a run on the viewed generation targets nothing', 'gen-1', 'gen-1', null],
        [
            'a run on a generation missing from the tree falls back to a short id',
            'trace-1',
            'gen-0123456789abcdef',
            { nodeId: 'gen-0123456789abcdef', label: 'gen-01234567...' },
        ],
    ])('%s', (_name, viewedNodeId, generationId, expected) => {
        const [result] = toEvalResults([run({ generation_id: generationId })], context({ viewedNodeId }))
        expect(result.target).toEqual(expected)
    })
})
