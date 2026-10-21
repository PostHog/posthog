import { EvaluationRun } from '../../../evaluations/types'
import type { TraceNodeApi } from '../../../generated/api.schemas'
import { EvalResult, EvalsState, NodeLoad } from '../types'
import { makeNodeDetail } from './testFixtures'
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

const run = (overrides: Partial<EvaluationRun> = {}): EvaluationRun => ({
    id: 'r1',
    evaluation_id: 'ev1',
    evaluation_name: 'Answers the question',
    generation_id: 'gen-1',
    trace_id: 'trace-1',
    timestamp: '2026-09-01T10:16:00Z',
    result: true,
    reasoning: 'Direct answer.',
    status: 'completed',
    ...overrides,
})

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
        evalRuns: [],
        evalRunsLoading: false,
        evaluations: [],
        detectorEvaluationIds: [],
        evaluationsSettled: true,
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
            evalRuns: [run(), run({ id: 'r2', generation_id: 'gen-other' })],
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

    it.each([
        ['eval runs are loading', { evalRunsLoading: true }],
        ['the evaluation configs that decide detector polarity have not loaded', { evaluationsSettled: false }],
    ])('reports evals as loading while %s', (_name, overrides) => {
        const detail = toNodeDetail({
            ...base,
            ...overrides,
            node: node('gen-1', 'generation'),
            load: { status: 'loading' },
            evalRuns: [run()],
        })
        expect(detail.evals).toEqual({ status: 'loading' })
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
    ])('trace root %s takes its time and session from the trace and shows every eval run', (_name, withEvent) => {
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
            evalRuns: [run(), run({ id: 'r2' })],
        })
        expect(detail.properties).toMatchObject({ timestamp: '2026-09-01T10:15:00Z', sessionId: 'sess-1' })
        expect(readyResults(detail.evals)).toHaveLength(2)
        expect(detail.content).toEqual({
            kind: 'io',
            input: withEvent ? { question: 'Hi' } : undefined,
            output: undefined,
        })
        expect(detail.raw === null).toBe(!withEvent)
    })

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
