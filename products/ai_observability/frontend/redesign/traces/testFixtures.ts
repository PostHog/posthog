import type { TraceListApi, TraceListItemApi } from '../../generated/api.schemas'

export function makeTraceListItem(overrides: Partial<TraceListItemApi> = {}): TraceListItemApi {
    return {
        id: 'trace-1',
        name: 'answer-billing-question',
        createdAt: '2026-09-01T10:15:00Z',
        sessionId: 'session-1',
        totals: {
            costUsd: 0.0021,
            inputTokens: 1840,
            outputTokens: 212,
            cacheReadTokens: null,
            cacheWriteTokens: null,
            latencyMs: 2310,
        },
        hasError: false,
        errorCount: 0,
        defaultNodeId: 'gen-1',
        firstError: null,
        toolsCalled: [],
        isSupportTrace: false,
        totalsPartial: false,
        review: null,
        ...overrides,
    }
}

export function makeTraceListPage(ids: string[], overrides: Partial<TraceListApi> = {}): TraceListApi {
    return {
        items: ids.map((id) => makeTraceListItem({ id })),
        counts: null,
        nextCursor: null,
        ...overrides,
    }
}
