import type { TraceNodeApi } from '../../../generated/api.schemas'
import { EvalResult, EvalsState, NodeLoad } from '../types'
import { makeEvaluationResult, makeNodeDetail } from './testFixtures'
import { toNodeDetail } from './toNodeDetail'

const node = (id: string, kind: 'trace' | 'span' | 'generation'): TraceNodeApi => ({
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

const result = (overrides: Parameters<typeof makeEvaluationResult>[0] = {}): ReturnType<typeof makeEvaluationResult> =>
    makeEvaluationResult({ targetNodeId: 'gen-1', ...overrides })

function readyResults(evals: EvalsState): EvalResult[] {
    if (evals.status !== 'ready') {
        throw new Error(`expected ready evals, got status "${evals.status}"`)
    }
    return evals.results
}

const ready = (detail: ReturnType<typeof makeNodeDetail>): NodeLoad => ({ status: 'ready', node: detail })

describe('toNodeDetail', () => {
    const base = {
        tree: [],
        evaluationResults: [],
        evaluationResultsFailed: false,
        teamId: 7,
        person: null,
        trace: { createdAt: '2026-09-01T10:15:00Z', sessionId: 'sess-1' },
    }

    it.each<[string, NodeLoad, unknown]>([
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
        expect(detail.raw).toBeNull()
        expect(detail.properties.timestamp).toBeNull()
    })

    it('generation reads its messages through the io keys and keeps its details, raw event and own evals', () => {
        const input = [{ role: 'user', content: 'Hi' }]
        const detail = toNodeDetail({
            ...base,
            node: node('gen-1', 'generation'),
            load: ready(
                makeNodeDetail({
                    id: 'gen-1',
                    properties: { $ai_input: input, $ai_output_choices: [{ role: 'assistant', content: 'Hello' }] },
                    ioKeys: { input: '$ai_input', output: '$ai_output_choices' },
                    metadata: { provider: 'openai', temperature: 0.2, sessionId: 'sess-9', promptVersion: 6 },
                })
            ),
            evaluationResults: [result(), result({ id: 'r2', targetNodeId: 'gen-other' })],
        })
        expect(detail.content).toMatchObject({
            kind: 'messages',
            input: [{ role: 'user', parts: [{ kind: 'text', text: 'Hi' }] }],
            output: [{ role: 'assistant', parts: [{ kind: 'text', text: 'Hello' }] }],
        })
        expect(detail.properties).toMatchObject({
            timestamp: '2026-09-01T10:15:02Z',
            provider: 'openai',
            temperature: 0.2,
            sessionId: 'sess-9',
            promptVersion: 6,
        })
        expect(detail.raw).toMatchObject({ event: '$ai_generation', uuid: 'gen-1', properties: { $ai_input: input } })
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

    it('span shows its state as input and output, surfaces its error and labels the person', () => {
        const detail = toNodeDetail({
            ...base,
            person: 'ana@example.com',
            node: node('span-1', 'span'),
            load: ready(
                makeNodeDetail({
                    id: 'span-1',
                    kind: 'span',
                    properties: { $ai_input_state: { q: 'x' } },
                    ioKeys: { input: '$ai_input_state' },
                    error: 'Timeout',
                })
            ),
        })
        expect(detail.content).toEqual({ kind: 'io', input: { q: 'x' }, output: undefined })
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
                load: ready(
                    makeNodeDetail({
                        id: 'trace-1',
                        kind: 'trace',
                        withEvent,
                        properties: { $ai_input_state: { question: 'Hi' } },
                        ioKeys: { input: '$ai_input_state' },
                    })
                ),
                evaluationResults: [result(), result({ id: 'r2' })],
            })
            expect(detail.properties).toMatchObject({ timestamp: '2026-09-01T10:15:00Z', sessionId: 'sess-1' })
            expect(readyResults(detail.evals)).toHaveLength(2)
            expect(detail.content).toEqual({
                kind: 'io',
                input: withEvent ? { question: 'Hi' } : undefined,
                output: undefined,
            })
            expect(detail.raw === null).toBe(!withEvent)
        }
    )

    it('renders an OTel span with a message array input and a text output as messages', () => {
        const detail = toNodeDetail({
            ...base,
            node: node('span-2', 'span'),
            load: ready(
                makeNodeDetail({
                    id: 'span-2',
                    kind: 'span',
                    properties: {
                        $ai_input: [{ role: 'user', content: 'Move my flight to Friday' }],
                        $ai_output_choices: 'Moved to Friday 09:15',
                    },
                    ioKeys: { input: '$ai_input', output: '$ai_output_choices' },
                })
            ),
        })
        expect(detail.content).toMatchObject({
            kind: 'messages',
            input: [{ role: 'user', parts: [{ kind: 'text', text: 'Move my flight to Friday' }] }],
            output: [{ role: 'assistant', parts: [{ kind: 'text', text: 'Moved to Friday 09:15' }] }],
        })
    })
})
