import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { traceEventsToShow } from './ticketAiTraceDetailLogic'

function event(id: string, name: string, properties: Record<string, any> = {}): LLMTraceEvent {
    return { id, event: name, createdAt: '2026-11-06T11:42:00Z', properties }
}

function trace(events: LLMTraceEvent[], overrides: Partial<LLMTrace> = {}): LLMTrace {
    return { id: 'trace-1', createdAt: '2026-11-06T11:42:00Z', distinctId: 'customer-1', events, ...overrides }
}

describe('traceEventsToShow', () => {
    test.each([
        [
            'LLM calls, ignoring spans',
            trace([event('span', '$ai_span', { $ai_input_state: 'q' }), event('gen', '$ai_generation')]),
            ['gen'],
        ],
        [
            'spans with a recorded state when there are no LLM calls',
            trace([event('empty-span', '$ai_span'), event('span', '$ai_span', { $ai_output_state: 'a' })]),
            ['span'],
        ],
        [
            'the root state when only the root recorded one',
            trace([], { inputState: 'q', outputState: 'a' }),
            ['trace-1'],
        ],
        ['nothing when no step recorded an input or output', trace([event('empty-span', '$ai_span')]), []],
    ])('shows %s', (_name, input, expectedIds) => {
        expect(traceEventsToShow(input).map((shown) => shown.id)).toEqual(expectedIds)
    })
})
