import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import type { TraceApi, TraceNodeStatsApi } from '../../../generated/api.schemas'

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

const emptyStats: TraceNodeStatsApi = {
    costUsd: null,
    inputTokens: null,
    outputTokens: null,
    cacheReadTokens: null,
    cacheWriteTokens: null,
    latencyMs: null,
}

export function makeTraceResource(overrides: Partial<TraceApi> = {}): TraceApi {
    const childIds = ['span-1', 'gen-1', 'gen-2']
    return {
        id: 'trace-1',
        name: 'answer-billing-question',
        createdAt: '2026-09-01T10:15:00Z',
        sessionId: null,
        person: { distinctId: 'user-1', label: 'ada@example.com' },
        totals: emptyStats,
        hasError: false,
        errorCount: 0,
        tree: [
            {
                id: 'trace-1',
                kind: 'trace',
                name: 'answer-billing-question',
                model: null,
                stats: emptyStats,
                hasError: false,
                children: childIds.map((id) => ({
                    id,
                    kind: id.startsWith('gen') ? 'generation' : 'span',
                    name: id,
                    model: null,
                    stats: emptyStats,
                    hasError: false,
                    children: [],
                })),
            },
        ],
        timeline: [],
        totalMs: 0,
        threadNodeIds: ['gen-2'],
        ...overrides,
    }
}
