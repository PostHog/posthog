/**
 * Table-tool tests — focused on preview-mode side-effect isolation. End-to-end
 * tabular behavior (membership, append, query, count, delete, truncate) is
 * covered by `agent-shared/src/memory/tabular-store.test.ts` against a real
 * S3 backend; this file exists to pin that mutating table tools short-circuit
 * before touching the store when the session is in preview mode.
 */
import { describe, expect, it, vi } from 'vitest'

import { HttpClient, type TabularStore, type ToolContext } from '@posthog/agent-shared'

import { tableAppendV1, tableCountV1, tableDeleteV1, tableTruncateV1 } from './table'

interface Envelope {
    ok: boolean
    error?: string
    code?: string
    data?: Record<string, unknown>
}

function previewCtxWithSpy(): { ctx: ToolContext; store: TabularStore } {
    // The store is keyed on (team_id, application_id) and not forked per
    // revision, so a draft preview would otherwise hit the same table the
    // live revision reads — assert each spy stays untouched.
    const spied: TabularStore = {
        listTables: vi.fn().mockResolvedValue([]),
        membership: vi.fn(),
        append: vi.fn(),
        query: vi.fn(),
        queryPage: vi.fn(),
        count: vi.fn().mockResolvedValue(0),
        delete: vi.fn(),
        truncate: vi.fn(),
    }
    const ctx: ToolContext = {
        teamId: 42,
        applicationId: 'app-test',
        sessionId: 'sess-preview',
        integrations: {},
        secret: () => undefined,
        secretAllowedHosts: () => undefined,
        log: () => undefined,
        tabularStore: spied,
        http: new HttpClient(),
        posthogApiBaseUrl: 'http://localhost:8010',
        isPreview: true,
    }
    return { ctx, store: spied }
}

describe('table tools — preview-mode side-effect isolation', () => {
    it('table-append returns synthetic counts ({appended: rows.length, skipped: 0}) and never calls store.append', async () => {
        const { ctx, store: spied } = previewCtxWithSpy()
        const r = (await tableAppendV1.run({ table: 'seen', rows: [{ id: 1 }, { id: 2 }, { id: 3 }] }, ctx)) as Envelope
        expect(r.ok).toBe(true)
        expect(r.data).toEqual({ appended: 3, skipped: 0 })
        expect(spied.append).not.toHaveBeenCalled()
    })

    it('table-delete returns deleted=0 and never calls store.delete', async () => {
        const { ctx, store: spied } = previewCtxWithSpy()
        const r = (await tableDeleteV1.run({ table: 'seen', where: { id: 1 } }, ctx)) as Envelope
        expect(r.ok).toBe(true)
        expect(r.data).toEqual({ deleted: 0 })
        expect(spied.delete).not.toHaveBeenCalled()
    })

    it('table-truncate returns truncated=<table> and never calls store.truncate', async () => {
        const { ctx, store: spied } = previewCtxWithSpy()
        const r = (await tableTruncateV1.run({ table: 'seen' }, ctx)) as Envelope
        expect(r.ok).toBe(true)
        expect(r.data).toEqual({ truncated: 'seen' })
        expect(spied.truncate).not.toHaveBeenCalled()
    })

    it('read tools (count / query / membership) still hit the store in preview — reads have no live-state effect', async () => {
        // Author must be able to verify the read paths during preview;
        // only writes are gated. Pinning this guards against an accidental
        // future overgeneralization that would block reads too.
        const { ctx, store: spied } = previewCtxWithSpy()
        await tableCountV1.run({ table: 'seen' }, ctx)
        expect(spied.count).toHaveBeenCalledTimes(1)
    })
})
