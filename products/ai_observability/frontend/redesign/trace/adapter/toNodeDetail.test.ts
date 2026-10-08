import { EvaluationRun } from '../../../evaluations/types'
import type { TraceNodeApi } from '../../../generated/api.schemas'
import { isLLMEvent } from '../../../utils'
import { EvalResult, EvalsState } from '../types'
import { makeEvent, makeTrace } from './testFixtures'
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

describe('toNodeDetail', () => {
    const base = {
        trace: makeTrace(),
        tree: [],
        cache: {},
        evalRuns: [],
        evalRunsLoading: false,
        evaluations: [],
        detectorEvaluationIds: [],
        evaluationsSettled: true,
        teamId: 7,
        person: null,
    }

    it('generation without inline IO and no cache entry yields loading', () => {
        const event = makeEvent({ id: 'gen-1', event: '$ai_generation', properties: {} })
        const detail = toNodeDetail({ ...base, event, node: node('gen-1', 'generation') })
        expect(detail.content).toEqual({ kind: 'loading' })
    })

    it('generation with content yields messages, properties and its own evals', () => {
        const event = makeEvent({
            id: 'gen-1',
            event: '$ai_generation',
            properties: {
                $ai_input: [{ role: 'user', content: 'Hi' }],
                $ai_output_choices: [{ role: 'assistant', content: 'Hello' }],
                $ai_model: 'gpt-4.1-mini',
                $ai_provider: 'openai',
                $ai_temperature: 0.2,
                $ai_session_id: 'sess-1',
                $ai_prompt_name: 'billing-answer',
                $ai_prompt_version: 6,
            },
        })
        const detail = toNodeDetail({
            ...base,
            event,
            node: node('gen-1', 'generation'),
            evalRuns: [run(), run({ id: 'r2', generation_id: 'gen-other' })],
        })
        expect(detail.content).toMatchObject({
            kind: 'messages',
            input: [{ role: 'user', parts: [{ kind: 'text', text: 'Hi' }] }],
            output: [{ role: 'assistant', parts: [{ kind: 'text', text: 'Hello' }] }],
        })
        expect(detail.properties).toMatchObject({
            provider: 'openai',
            temperature: 0.2,
            sessionId: 'sess-1',
            promptVersion: 6,
        })
        expect(readyResults(detail.evals).map((result) => result.id)).toEqual(['r1'])
    })

    it.each([
        ['eval runs are loading', { evalRunsLoading: true }],
        ['the evaluation configs that decide detector polarity have not loaded', { evaluationsSettled: false }],
    ])('reports evals as loading while %s', (_name, overrides) => {
        const event = makeEvent({ id: 'gen-1', event: '$ai_generation', properties: {} })
        const detail = toNodeDetail({
            ...base,
            ...overrides,
            event,
            node: node('gen-1', 'generation'),
            evalRuns: [run()],
        })
        expect(detail.evals).toEqual({ status: 'loading' })
    })

    it.each([
        { name: 'a person label', person: 'ana@example.com' },
        { name: 'no person', person: null },
    ])(
        'span shows its state as input and output, surfaces its error, and labels the person with $name',
        ({ person }) => {
            const event = makeEvent({
                id: 'span-1',
                properties: {
                    $ai_input_state: { q: 'x' },
                    $ai_output_state: null,
                    $ai_is_error: true,
                    $ai_error: 'Timeout',
                },
            })
            const detail = toNodeDetail({ ...base, event, node: node('span-1', 'span'), person })
            expect(detail.content).toEqual({ kind: 'io', input: { q: 'x' }, output: undefined })
            expect(detail.error).toBe('Timeout')
            expect(detail.properties.person).toBe(person)
        }
    )

    it('trace root shows the trace state and every eval run', () => {
        const trace = makeTrace({ inputState: { question: 'Hi' }, outputState: { answer: 'Hello' } })
        const detail = toNodeDetail({
            ...base,
            trace,
            event: trace,
            node: node('trace-1', 'trace'),
            evalRuns: [run(), run({ id: 'r2' })],
        })
        expect(detail.content).toEqual({ kind: 'io', input: { question: 'Hi' }, output: { answer: 'Hello' } })
        expect(readyResults(detail.evals)).toHaveLength(2)
        expect(detail.raw).not.toHaveProperty('events')
    })

    it.each([
        {
            name: 'trace state holding message arrays',
            event: makeTrace({
                inputState: [{ role: 'user', content: 'Move my flight to Friday' }],
                outputState: [{ role: 'assistant', content: 'Moved to Friday 09:15' }],
            }),
            kind: 'trace' as const,
        },
        {
            name: 'an OTel span with a message array input and a text output',
            event: makeEvent({
                id: 'span-2',
                properties: {
                    $ai_input: [{ role: 'user', content: 'Move my flight to Friday' }],
                    $ai_output_choices: 'Moved to Friday 09:15',
                },
            }),
            kind: 'span' as const,
        },
    ])('renders $name as input and output messages', ({ event, kind }) => {
        const trace = isLLMEvent(event) ? base.trace : event
        const detail = toNodeDetail({
            ...base,
            trace,
            event,
            node: node(isLLMEvent(event) ? event.id : trace.id, kind),
        })
        expect(detail.content).toMatchObject({
            kind: 'messages',
            input: [{ role: 'user', parts: [{ kind: 'text', text: 'Move my flight to Friday' }] }],
            output: [{ role: 'assistant', parts: [{ kind: 'text', text: 'Moved to Friday 09:15' }] }],
        })
    })
})
