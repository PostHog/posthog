import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { EnrichedTraceTreeNode } from '../../../aiObservabilityTraceDataLogic'

export function makeEvent(overrides: Partial<LLMTraceEvent> & { id: string }): LLMTraceEvent {
    return { event: '$ai_span', properties: {}, createdAt: '2026-09-01T10:15:00Z', ...overrides }
}

export function makeTrace(overrides: Partial<LLMTrace> = {}): LLMTrace {
    return {
        id: 'trace-1',
        createdAt: '2026-09-01T10:15:00Z',
        distinctId: 'user-ana',
        traceName: 'answer-billing-question',
        totalCost: 0.0021,
        inputTokens: 1840,
        outputTokens: 212,
        totalLatency: 2.31,
        events: [],
        ...overrides,
    }
}

export function enrich(
    event: LLMTraceEvent,
    children: EnrichedTraceTreeNode[] = [],
    display: Partial<Pick<EnrichedTraceTreeNode, 'displayTotalCost' | 'displayLatency' | 'aggregation'>> = {}
): EnrichedTraceTreeNode {
    return {
        event,
        children,
        displayTotalCost: display.displayTotalCost ?? null,
        displayLatency: display.displayLatency ?? 0,
        displayUsage: null,
        attachedFeedback: [],
        aggregation: display.aggregation,
    }
}
