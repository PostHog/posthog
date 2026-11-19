import type { MockSignature } from '~/mocks/utils'

import type { SessionListApi, SessionListItemApi } from '../../generated/api.schemas'
import { TRACE_CELL_URLS, traceCellsMocks } from '../traces/testFixtures'

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
