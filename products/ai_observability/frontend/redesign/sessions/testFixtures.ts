import type { MockSignature } from '~/mocks/utils'

import type {
    SessionListApi,
    SessionListItemApi,
    SessionPageRequestApi,
    SessionPersonItemApi,
    SessionPreviewApi,
    SessionTurnApi,
    SessionTurnPageApi,
    TraceMessageApi,
    TraceTurnApi,
    TraceTurnsRequestApi,
} from '../../generated/api.schemas'
import { makeMessage } from '../trace/testFixtures'
import { makeTraceListItem } from '../traces/testFixtures'
import type { SessionCellRead } from './sessionCellsLogic'

export const SESSION_TURNS_URL = '/api/projects/:team_id/ai_observability/sessions/:id/turns/'

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
        totalsPartial: false,
        ...overrides,
    }
}

export function makeSessionListPage(ids: string[], overrides: Partial<SessionListApi> = {}): SessionListApi {
    return { items: ids.map((id) => makeSessionListItem({ id })), nextCursor: null, ...overrides }
}

export const SESSION_CELL_URLS: Record<SessionCellRead, string> = {
    titles: '/api/projects/:team_id/ai_observability/sessions/previews/',
    people: '/api/projects/:team_id/ai_observability/sessions/people/',
}

export function makeSessionPreview(sessionId: string, overrides: Partial<SessionPreviewApi> = {}): SessionPreviewApi {
    return { sessionId, input: 'Why was I charged twice this month?', inputMissingReason: null, ...overrides }
}

export function makeSessionPersonItem(
    sessionId: string,
    overrides: Partial<SessionPersonItemApi> = {}
): SessionPersonItemApi {
    return { sessionId, person: { distinctId: 'ana@example.com', label: 'Ana Example' }, ...overrides }
}

export function makeSessionCellsAnswer(
    read: SessionCellRead,
    sessionIds: string[]
): { items: (SessionPreviewApi | SessionPersonItemApi)[] } {
    const makeItem = read === 'titles' ? makeSessionPreview : makeSessionPersonItem
    return { items: sessionIds.map((sessionId) => makeItem(sessionId)) }
}

function answering(read: SessionCellRead): MockSignature {
    return async ({ request }: { request: Request }) => {
        const { session_ids }: SessionPageRequestApi = await request.json()
        return [200, makeSessionCellsAnswer(read, session_ids)]
    }
}

export function sessionCellsMocks(): Record<string, MockSignature> {
    return {
        [SESSION_CELL_URLS.titles]: answering('titles'),
        [SESSION_CELL_URLS.people]: answering('people'),
    }
}

export const TRACE_TURNS_URL = '/api/projects/:team_id/ai_observability/traces/turns/'

const TURN_START_MS = Date.parse('2026-09-01T10:15:00Z')
const TURN_GAP_MS = 60_000

function turnMessage(traceId: string, role: 'user' | 'assistant', text: string): TraceMessageApi {
    return makeMessage({
        id: `${traceId}-${role}`,
        role,
        parts: [{ kind: 'text', text }],
        sourceNodeId: `${traceId}-gen`,
    })
}

export function makeSessionTurn(overrides: Partial<SessionTurnApi> = {}): SessionTurnApi {
    return { ...makeTraceListItem(), waitSlow: false, silenceBeforeMs: null, ...overrides }
}

/** The row of turn `index` of a session, one minute after the turn before it. */
function makeSessionTurnRow(index: number): SessionTurnApi {
    const id = `trace-${index}`
    return makeSessionTurn({
        id,
        createdAt: new Date(TURN_START_MS + index * TURN_GAP_MS).toISOString(),
        defaultNodeId: `${id}-gen`,
    })
}

export function makeSessionTurnPage(
    indexes: number[],
    overrides: Partial<SessionTurnPageApi> = {}
): SessionTurnPageApi {
    return {
        items: indexes.map((index) => makeSessionTurnRow(index)),
        nextCursor: null,
        previousCursor: null,
        ...overrides,
    }
}

/** The question and answer of the turn of trace `traceId`. */
export function makeTraceTurn(traceId: string, overrides: Partial<TraceTurnApi> = {}): TraceTurnApi {
    return {
        traceId,
        input: { kind: 'messages', messages: [turnMessage(traceId, 'user', `Question of ${traceId}`)] },
        output: { kind: 'messages', messages: [turnMessage(traceId, 'assistant', `Answer of ${traceId}`)] },
        inputMissingReason: null,
        outputMissingReason: null,
        ...overrides,
    }
}

/** Answers `traces/turns/` with the question and answer of each requested trace. */
export function traceTurnsMocks(): Record<string, MockSignature> {
    return {
        [TRACE_TURNS_URL]: async ({ request }: { request: Request }) => {
            const { trace_ids }: TraceTurnsRequestApi = await request.json()
            return [200, { items: trace_ids.map((traceId) => makeTraceTurn(traceId)) }]
        },
    }
}
