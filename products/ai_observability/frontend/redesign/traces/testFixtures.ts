import type { MockSignature } from '~/mocks/utils'

import type {
    TraceListApi,
    TraceListItemApi,
    TracePersonItemApi,
    TracePreviewApi,
    TraceSentimentItemApi,
} from '../../generated/api.schemas'
import type { TracesTableCells } from './components/TracesTableColumns'
import type { TraceCellRead } from './traceCellsLogic'
import type { TraceCellLoad } from './types'

export const TRACE_CELL_URLS: Record<TraceCellRead, string> = {
    previews: '/api/projects/:team_id/ai_observability/traces/previews/',
    people: '/api/projects/:team_id/ai_observability/traces/people/',
    sentiment: '/api/projects/:team_id/ai_observability/traces/sentiment/',
}

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
        costAndLatencyPartial: false,
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

export function makeTracePreview(traceId: string, overrides: Partial<TracePreviewApi> = {}): TracePreviewApi {
    return {
        traceId,
        input: 'Why was I charged twice this month?',
        output: 'You were charged once for your plan and once for extra seats added on the 12th.',
        inputMissingReason: null,
        outputMissingReason: null,
        ...overrides,
    }
}

export function makeTracePersonItem(traceId: string, overrides: Partial<TracePersonItemApi> = {}): TracePersonItemApi {
    return { traceId, person: { distinctId: 'ana@example.com', label: 'Ana Example' }, ...overrides }
}

export function makeTraceSentimentItem(
    traceId: string,
    overrides: Partial<TraceSentimentItemApi> = {}
): TraceSentimentItemApi {
    return { traceId, sentiment: { label: 'positive', score: 0.82 }, ...overrides }
}

export function makeTraceCellsAnswer(
    read: TraceCellRead,
    traceIds: string[]
): { items: (TracePreviewApi | TracePersonItemApi | TraceSentimentItemApi)[] } {
    const makeItem = { previews: makeTracePreview, people: makeTracePersonItem, sentiment: makeTraceSentimentItem }[
        read
    ]
    return { items: traceIds.map((traceId) => makeItem(traceId)) }
}

function answering(read: TraceCellRead): MockSignature {
    return async ({ request }: { request: Request }) => {
        const { trace_ids }: { trace_ids: string[] } = await request.json()
        return [200, makeTraceCellsAnswer(read, trace_ids)]
    }
}

export function traceCellsMocks(): Record<string, MockSignature> {
    return {
        [TRACE_CELL_URLS.previews]: answering('previews'),
        [TRACE_CELL_URLS.people]: answering('people'),
        [TRACE_CELL_URLS.sentiment]: answering('sentiment'),
    }
}

export function ready<T>(value: T): TraceCellLoad<T> {
    return { status: 'ready', value }
}

/** The three cells of each trace, read with the default previews, person and sentiment. */
export function makeLoadedTraceCells(traceIds: string[]): TracesTableCells {
    return {
        previews: new Map(traceIds.map((traceId) => [traceId, ready(makeTracePreview(traceId))])),
        people: new Map(traceIds.map((traceId) => [traceId, ready(makeTracePersonItem(traceId).person)])),
        sentiments: new Map(traceIds.map((traceId) => [traceId, ready(makeTraceSentimentItem(traceId).sentiment)])),
    }
}

/** The three cells of each trace, still loading or failed. */
export function makeUnreadTraceCells(traceIds: string[], status: 'loading' | 'error'): TracesTableCells {
    return {
        previews: new Map(traceIds.map((traceId) => [traceId, { status }])),
        people: new Map(traceIds.map((traceId) => [traceId, { status }])),
        sentiments: new Map(traceIds.map((traceId) => [traceId, { status }])),
    }
}
