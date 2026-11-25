import type { MockSignature } from '~/mocks/utils'

import type {
    SessionListApi,
    SessionListItemApi,
    SessionPageRequestApi,
    SessionPersonItemApi,
    SessionPreviewApi,
} from '../../generated/api.schemas'
import type { SessionCellRead } from './sessionCellsLogic'

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
