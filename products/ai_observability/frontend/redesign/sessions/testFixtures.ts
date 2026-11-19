import type { MockSignature } from '~/mocks/utils'

import type {
    SessionListApi,
    SessionListItemApi,
    TraceListApi,
    TraceListItemApi,
    TraceTurnApi,
} from '../../generated/api.schemas'
import { makeMessage } from '../trace/testFixtures'
import { TRACE_CELL_URLS, makeTraceListItem, traceCellsMocks } from '../traces/testFixtures'

export const SESSION_TRACES_URL = '/api/projects/:team_id/ai_observability/traces/'
export const SESSION_TURNS_URL = '/api/projects/:team_id/ai_observability/traces/turns/'

export function makeSessionListItem(overrides: Partial<SessionListItemApi> = {}): SessionListItemApi {
    return {
        id: 'session-1',
        firstSeen: '2026-09-01T10:15:00Z',
        lastSeen: '2026-09-01T10:42:00Z',
        durationMs: 1_620_000,
        turnCount: 6,
        totals: {
            costUsd: 0.0126,
            inputTokens: 11_040,
            outputTokens: 1_272,
            cacheReadTokens: null,
            cacheWriteTokens: null,
            latencyMs: 13_860,
        },
        erroredTurns: 0,
        distinctId: 'ana@example.com',
        firstTraceId: `${overrides.id ?? 'session-1'}-first-trace`,
        firstTraceCreatedAt: '2026-09-01T10:15:00Z',
        ...overrides,
    }
}

export function makeSessionListPage(ids: string[], overrides: Partial<SessionListApi> = {}): SessionListApi {
    return { items: ids.map((id) => makeSessionListItem({ id })), nextCursor: null, ...overrides }
}

export function sessionCellsMocks(): Record<string, MockSignature> {
    const mocks = traceCellsMocks()
    return {
        [TRACE_CELL_URLS.previews]: mocks[TRACE_CELL_URLS.previews],
        [TRACE_CELL_URLS.people]: mocks[TRACE_CELL_URLS.people],
    }
}

const TURN_START_MS = Date.parse('2026-09-01T10:15:00Z')
const TURN_GAP_MS = 60_000

/** Turn `index` of a session, one minute after the turn before it. */
export function makeSessionTurnItem(index: number, overrides: Partial<TraceListItemApi> = {}): TraceListItemApi {
    const id = `trace-${index}`
    return makeTraceListItem({
        id,
        createdAt: new Date(TURN_START_MS + index * TURN_GAP_MS).toISOString(),
        defaultNodeId: `${id}-gen`,
        ...overrides,
    })
}

export function makeSessionTurnsPage(indexes: number[], overrides: Partial<TraceListApi> = {}): TraceListApi {
    return {
        items: indexes.map((index) => makeSessionTurnItem(index)),
        counts: null,
        nextCursor: null,
        previousCursor: null,
        ...overrides,
    }
}

export function makeTraceTurn(traceId: string, overrides: Partial<TraceTurnApi> = {}): TraceTurnApi {
    return {
        traceId,
        input: {
            kind: 'messages',
            messages: [
                makeMessage({
                    id: `${traceId}-question`,
                    role: 'user',
                    parts: [{ kind: 'text', text: `Question of ${traceId}` }],
                    sourceNodeId: `${traceId}-gen`,
                }),
            ],
        },
        output: {
            kind: 'messages',
            messages: [
                makeMessage({
                    id: `${traceId}-answer`,
                    role: 'assistant',
                    parts: [{ kind: 'text', text: `Answer of ${traceId}` }],
                    sourceNodeId: `${traceId}-gen`,
                }),
            ],
        },
        inputMissingReason: null,
        outputMissingReason: null,
        ...overrides,
    }
}

/** Answers a turns read with a turn for each requested trace. */
export function sessionTurnsMock(): MockSignature {
    return async ({ request }: { request: Request }) => {
        const { trace_ids }: { trace_ids: string[] } = await request.json()
        return [200, { items: trace_ids.map((traceId) => makeTraceTurn(traceId)) }]
    }
}
