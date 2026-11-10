import type { TraceEvaluationResultApi, TraceNodeApi, TraceNodeDetailApi } from '../../../generated/api.schemas'
import { EvalResult, EvalsState, NodeContent, NodeLoad } from '../types'
import { makeEvaluationResult, makeMessage, makeNodeDetail } from './testFixtures'
import { toNodeDetail } from './toNodeDetail'

const node = (id: string, kind: TraceNodeApi['kind']): TraceNodeApi => ({
    id,
    kind,
    name: id,
    model: null,
    hasError: false,
    children: [],
    stats: {
        costUsd: null,
        inputTokens: null,
        outputTokens: null,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        latencyMs: null,
    },
})

const result = (overrides: Partial<TraceEvaluationResultApi> = {}): TraceEvaluationResultApi =>
    makeEvaluationResult({ targetNodeId: 'gen-1', ...overrides })

function readyResults(evals: EvalsState): EvalResult[] {
    if (evals.status !== 'ready') {
        throw new Error(`expected ready evals, got status "${evals.status}"`)
    }
    return evals.results
}

const ready = (detail: TraceNodeDetailApi): NodeLoad => ({ status: 'ready', node: detail })

describe('toNodeDetail', () => {
    const base = {
        tree: [],
        evaluationResults: [],
        evaluationResultsFailed: false,
        person: null,
        trace: { createdAt: '2026-09-01T10:15:00Z', sessionId: 'sess-1' },
    }

    it.each<[string, NodeLoad, NodeContent]>([
        ['loading', { status: 'loading' }, { kind: 'loading' }],
        [
            'not found',
            { status: 'error', failure: 'not_found' },
            {
                kind: 'error',
                message:
                    'This step could not be found. It may have been deleted, or it is outside the retention period.',
            },
        ],
        [
            'failed',
            { status: 'error', failure: 'failed' },
            { kind: 'error', message: 'This step could not be loaded. Select it again to retry.' },
        ],
    ])('a %s node shows its load state, no raw event and no time', (_name, load, content) => {
        const detail = toNodeDetail({ ...base, node: node('gen-1', 'generation'), load })
        expect(detail.content).toEqual(content)
        expect(detail.properties.timestamp).toBeNull()
    })

    it('passes the node content through and keeps the details and own evals', () => {
        const content = {
            input: { kind: 'messages' as const, messages: [makeMessage({ id: 'ask', role: 'user' })] },
            output: { kind: 'json' as const, value: { answer: 'Hello' } },
        }
        const detail = toNodeDetail({
            ...base,
            node: node('gen-1', 'generation'),
            load: ready(
                makeNodeDetail({
                    id: 'gen-1',
                    content,
                    metadata: { provider: 'openai', temperature: 0.2, sessionId: 'sess-9', promptVersion: 6 },
                })
            ),
            evaluationResults: [result(), result({ id: 'r2', targetNodeId: 'gen-other' })],
        })
        expect(detail.content).toEqual({ kind: 'loaded', ...content })
        expect(detail.properties).toMatchObject({
            timestamp: '2026-09-01T10:15:02Z',
            provider: 'openai',
            temperature: 0.2,
            sessionId: 'sess-9',
            promptVersion: 6,
        })
        expect(readyResults(detail.evals).map((result) => result.id)).toEqual(['r1'])
    })

    it.each<[string, { evaluationResults: null; evaluationResultsFailed: boolean }, EvalsState]>([
        [
            'loading until the results arrive',
            { evaluationResults: null, evaluationResultsFailed: false },
            { status: 'loading' },
        ],
        [
            'an error when the read fails',
            { evaluationResults: null, evaluationResultsFailed: true },
            { status: 'error', errorMessage: 'Evaluation results could not be loaded. Reload the page to try again.' },
        ],
    ])('reports evals as %s', (_name, overrides, evals) => {
        const detail = toNodeDetail({
            ...base,
            ...overrides,
            node: node('gen-1', 'generation'),
            load: { status: 'loading' },
        })
        expect(detail.evals).toEqual(evals)
    })

    it('surfaces the error of a span and labels the person', () => {
        const detail = toNodeDetail({
            ...base,
            person: 'ana@example.com',
            node: node('span-1', 'span'),
            load: ready(makeNodeDetail({ id: 'span-1', kind: 'span', error: 'Timeout' })),
        })
        expect(detail.error).toBe('Timeout')
        expect(detail.properties.person).toBe('ana@example.com')
    })

    it.each([
        ['with a trace event', true],
        ['without a trace event', false],
    ])(
        'trace root %s takes its time and session from the trace and shows every evaluation result',
        (_name, withEvent) => {
            const detail = toNodeDetail({
                ...base,
                node: node('trace-1', 'trace'),
                load: ready(makeNodeDetail({ id: 'trace-1', kind: 'trace', withEvent })),
                evaluationResults: [result(), result({ id: 'r2' })],
            })
            expect(detail.properties).toMatchObject({ timestamp: '2026-09-01T10:15:00Z', sessionId: 'sess-1' })
            expect(readyResults(detail.evals)).toHaveLength(2)
        }
    )
})
