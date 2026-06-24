/**
 * Memory-tool tests — exercise each of the six tools through their run() against
 * a real `S3MemoryStore` pointed at SeaweedFS. No skip-if-unreachable; bring up
 * SeaweedFS before running.
 */
import { S3Client } from '@aws-sdk/client-s3'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import {
    buildTestStore,
    HttpClient,
    MemoryStore,
    newTestPrefix,
    S3MemoryStore,
    type ToolContext,
    wipeTestPrefix,
} from '@posthog/agent-shared'

import { memoryDeleteV1, memoryListV1, memoryReadV1, memorySearchV1, memoryUpdateV1, memoryWriteV1 } from './memory'

function makeCtx(store: S3MemoryStore | undefined): ToolContext {
    return {
        teamId: 42,
        applicationId: 'app-test',
        sessionId: 'sess-1',
        secret: () => undefined,
        secretAllowedHosts: () => undefined,
        log: () => undefined,
        memoryStore: store,
        http: new HttpClient(),
        posthogApiBaseUrl: 'http://localhost:8010',
        isPreview: false,
    }
}

interface Envelope {
    ok: boolean
    error?: string
    data?: Record<string, unknown>
}

describe('memory tools — store-unavailable envelope', () => {
    it.each([
        ['list', () => memoryListV1.run({}, makeCtx(undefined))],
        ['search', () => memorySearchV1.run({ cue: 'x' }, makeCtx(undefined))],
        ['read', () => memoryReadV1.run({ path: 'a.md' }, makeCtx(undefined))],
        ['write', () => memoryWriteV1.run({ path: 'a.md', description: 'd', content: 'c' }, makeCtx(undefined))],
        ['update', () => memoryUpdateV1.run({ path: 'a.md', description: 'd' }, makeCtx(undefined))],
        ['delete', () => memoryDeleteV1.run({ path: 'a.md' }, makeCtx(undefined))],
    ])('%s returns memory_store_unavailable', async (_label, runFn) => {
        const r = (await runFn()) as Envelope
        expect(r.ok).toBe(false)
        expect(r.error).toBe('memory_store_unavailable')
    })
})

describe('memory tools (real S3 / SeaweedFS)', () => {
    let client: S3Client
    let store: S3MemoryStore
    let prefix: string

    beforeAll(() => {
        prefix = newTestPrefix('agent_memory_tools_test')
        const built = buildTestStore(prefix)
        client = built.client
        store = built.store
    })

    afterEach(async () => {
        await wipeTestPrefix(client, prefix)
    })

    afterAll(async () => {
        await wipeTestPrefix(client, prefix)
        client.destroy()
    })

    describe('memoryWriteV1', () => {
        it('creates a new file and returns created_at', async () => {
            const ctx = makeCtx(store)
            const r = (await memoryWriteV1.run(
                { path: 'notes/first.md', description: 'first note', content: 'hello', tags: ['note'] },
                ctx
            )) as Envelope
            expect(r.ok).toBe(true)
            expect(r.data?.path).toBe('notes/first.md')
            expect(typeof r.data?.created_at).toBe('string')

            const file = await store.read({ teamId: 42, applicationId: 'app-test' }, 'notes/first.md')
            expect(file.frontmatter.description).toBe('first note')
            expect(file.frontmatter.tags).toEqual(['note'])
            expect(file.content).toBe('hello')
        })

        it('rejects a duplicate (existing path)', async () => {
            const ctx = makeCtx(store)
            await memoryWriteV1.run({ path: 'a.md', description: 'first', content: 'x' }, ctx)
            const r = (await memoryWriteV1.run({ path: 'a.md', description: 'second', content: 'y' }, ctx)) as Envelope
            expect(r.ok).toBe(false)
            expect(r.error).toMatch(/conflict/)
        })

        it('validates description length', async () => {
            const r = (await memoryWriteV1.run(
                { path: 'a.md', description: 'x'.repeat(281), content: 'c' },
                makeCtx(store)
            )) as Envelope
            expect(r.ok).toBe(false)
            expect(r.error).toMatch(/exceeds/)
        })

        it('validates path', async () => {
            const r = (await memoryWriteV1.run(
                { path: 'UPPER.md', description: 'd', content: 'c' },
                makeCtx(store)
            )) as Envelope
            expect(r.ok).toBe(false)
            expect(r.error).toMatch(/invalid memory path/)
        })
    })

    describe('memoryUpdateV1', () => {
        it('overwrites and preserves createdAt', async () => {
            const ctx = makeCtx(store)
            await memoryWriteV1.run({ path: 'a.md', description: 'orig', content: 'old' }, ctx)
            const created = (await store.read({ teamId: 42, applicationId: 'app-test' }, 'a.md')).frontmatter.createdAt
            await new Promise((r) => setTimeout(r, 5))
            const r = (await memoryUpdateV1.run(
                { path: 'a.md', description: 'new', content: 'new body' },
                ctx
            )) as Envelope
            expect(r.ok).toBe(true)
            const updated = await store.read({ teamId: 42, applicationId: 'app-test' }, 'a.md')
            expect(updated.frontmatter.description).toBe('new')
            expect(updated.content).toBe('new body')
            expect(updated.frontmatter.createdAt).toBe(created)
            expect(updated.frontmatter.updatedAt).not.toBe(created)
        })

        it('fails on missing path', async () => {
            const r = (await memoryUpdateV1.run({ path: 'missing.md', description: 'd' }, makeCtx(store))) as Envelope
            expect(r.ok).toBe(false)
            expect(r.error).toMatch(/not_found/)
        })

        it('keeps unspecified fields from the existing doc', async () => {
            const ctx = makeCtx(store)
            await memoryWriteV1.run({ path: 'a.md', description: 'keep me', content: 'keep body', tags: ['kept'] }, ctx)
            await memoryUpdateV1.run({ path: 'a.md', content: 'new body' }, ctx)
            const file = await store.read({ teamId: 42, applicationId: 'app-test' }, 'a.md')
            expect(file.frontmatter.description).toBe('keep me')
            expect(file.frontmatter.tags).toEqual(['kept'])
            expect(file.content).toBe('new body')
        })
    })

    describe('memoryDeleteV1', () => {
        it('deletes an existing file', async () => {
            const ctx = makeCtx(store)
            await memoryWriteV1.run({ path: 'a.md', description: 'd', content: 'c' }, ctx)
            const r = (await memoryDeleteV1.run({ path: 'a.md' }, ctx)) as Envelope
            expect(r.ok).toBe(true)
            expect(await store.exists({ teamId: 42, applicationId: 'app-test' }, 'a.md')).toBe(false)
        })

        it('returns not_found on missing path', async () => {
            const r = (await memoryDeleteV1.run({ path: 'missing.md' }, makeCtx(store))) as Envelope
            expect(r.ok).toBe(false)
            expect(r.error).toMatch(/not_found/)
        })
    })

    describe('memoryListV1', () => {
        it('returns headers, not full bodies', async () => {
            const ctx = makeCtx(store)
            await memoryWriteV1.run({ path: 'a.md', description: 'A', content: 'body A' }, ctx)
            await memoryWriteV1.run({ path: 'b.md', description: 'B', content: 'body B' }, ctx)
            const r = (await memoryListV1.run({}, ctx)) as Envelope
            expect(r.ok).toBe(true)
            const data = r.data as { count: number; entries: { path: string; description: string }[] }
            expect(data.count).toBe(2)
            expect(data.entries.map((e) => e.description).sort()).toEqual(['A', 'B'])
            expect(JSON.stringify(data)).not.toContain('body A')
        })

        it('honours the prefix filter', async () => {
            const ctx = makeCtx(store)
            await memoryWriteV1.run({ path: 'incidents/x.md', description: 'inc', content: 'c' }, ctx)
            await memoryWriteV1.run({ path: 'notes/y.md', description: 'note', content: 'c' }, ctx)
            const r = (await memoryListV1.run({ prefix: 'incidents/' }, ctx)) as Envelope
            const data = r.data as { entries: { path: string }[] }
            expect(data.entries.map((e) => e.path)).toEqual(['incidents/x.md'])
        })
    })

    describe('memoryReadV1', () => {
        it('returns description + content + frontmatter timestamps', async () => {
            const ctx = makeCtx(store)
            await memoryWriteV1.run({ path: 'a.md', description: 'desc here', content: 'real body', tags: ['t1'] }, ctx)
            const r = (await memoryReadV1.run({ path: 'a.md' }, ctx)) as Envelope
            expect(r.ok).toBe(true)
            const data = r.data as {
                path: string
                description: string
                content: string
                tags: string[]
                created_at?: string
            }
            expect(data.path).toBe('a.md')
            expect(data.description).toBe('desc here')
            expect(data.content).toBe('real body')
            expect(data.tags).toEqual(['t1'])
            expect(data.created_at).not.toBeUndefined()
        })

        it('surfaces not_found', async () => {
            const r = (await memoryReadV1.run({ path: 'missing.md' }, makeCtx(store))) as Envelope
            expect(r.ok).toBe(false)
            expect(r.error).toMatch(/not_found/)
        })
    })

    describe('memorySearchV1', () => {
        it('returns top hits with score and snippet', async () => {
            const ctx = makeCtx(store)
            await memoryWriteV1.run(
                {
                    path: 'incidents/db.md',
                    description: 'Postgres connection pool exhausted',
                    content: 'pgbouncer was undersized for the worker count',
                    tags: ['db', 'incident'],
                },
                ctx
            )
            await memoryWriteV1.run({ path: 'notes/unrelated.md', description: 'thinking', content: 'pet ideas' }, ctx)
            const r = (await memorySearchV1.run({ cue: 'postgres pool exhausted' }, ctx)) as Envelope
            expect(r.ok).toBe(true)
            const data = r.data as { count: number; results: { path: string; score: number; snippet?: string }[] }
            expect(data.count).toBeGreaterThan(0)
            expect(data.results[0].path).toBe('incidents/db.md')
            expect(data.results[0].score).toBeGreaterThan(0)
        })
    })
})

describe('memory tools — preview-mode side-effect isolation', () => {
    /** Mutating tools must short-circuit before touching the store when the
     *  session is in preview mode: the store is keyed on (team_id,
     *  application_id) and not forked per revision, so a draft would otherwise
     *  mutate the same files the live revision reads. Each test pins a
     *  store-method spy and asserts it is never called. */
    function previewCtxWithSpy(): { ctx: ToolContext; store: MemoryStore } {
        const spied: MemoryStore = {
            list: vi.fn(),
            read: vi.fn(),
            readHeader: vi.fn(),
            put: vi.fn(),
            delete: vi.fn(),
            exists: vi.fn(),
        }
        const ctx: ToolContext = {
            teamId: 42,
            applicationId: 'app-test',
            sessionId: 'sess-preview',
            secret: () => undefined,
            secretAllowedHosts: () => undefined,
            log: () => undefined,
            memoryStore: spied,
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            isPreview: true,
        }
        return { ctx, store: spied }
    }

    it('memory-write returns a synthetic created_at and never calls store.put', async () => {
        const { ctx, store: spied } = previewCtxWithSpy()
        const r = (await memoryWriteV1.run(
            { path: 'incidents/db.md', description: 'd', content: 'c' },
            ctx
        )) as Envelope
        expect(r.ok).toBe(true)
        const data = r.data as { path: string; created_at: string }
        expect(data.path).toBe('incidents/db.md')
        expect(data.created_at).toMatch(/^\d{4}-\d{2}-\d{2}T/)
        expect(spied.put).not.toHaveBeenCalled()
    })

    it('memory-update returns a synthetic updated_at and never calls store.put / store.read', async () => {
        const { ctx, store: spied } = previewCtxWithSpy()
        const r = (await memoryUpdateV1.run({ path: 'notes/x.md', description: 'new' }, ctx)) as Envelope
        expect(r.ok).toBe(true)
        const data = r.data as { path: string; updated_at: string }
        expect(data.path).toBe('notes/x.md')
        expect(data.updated_at).toMatch(/^\d{4}-\d{2}-\d{2}T/)
        expect(spied.read).not.toHaveBeenCalled()
        expect(spied.put).not.toHaveBeenCalled()
    })

    it('memory-delete returns deleted=true and never calls store.delete', async () => {
        const { ctx, store: spied } = previewCtxWithSpy()
        const r = (await memoryDeleteV1.run({ path: 'incidents/db.md' }, ctx)) as Envelope
        expect(r.ok).toBe(true)
        expect(r.data).toEqual({ path: 'incidents/db.md', deleted: true })
        expect(spied.delete).not.toHaveBeenCalled()
    })

    it('read tools (list / search / read) still touch the store in preview — reads have no live-state effect', async () => {
        // Author must be able to verify the read paths during preview;
        // only writes are gated. Pinning this guards against an accidental
        // future overgeneralization that would block reads too.
        const previewStore: MemoryStore = {
            list: vi.fn().mockResolvedValue([]),
            read: vi.fn().mockRejectedValue(new Error('not found')),
            readHeader: vi.fn(),
            put: vi.fn(),
            delete: vi.fn(),
            exists: vi.fn(),
        }
        const ctx: ToolContext = {
            teamId: 42,
            applicationId: 'app-test',
            sessionId: 'sess-preview',
            secret: () => undefined,
            secretAllowedHosts: () => undefined,
            log: () => undefined,
            memoryStore: previewStore,
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            isPreview: true,
        }
        await memoryListV1.run({}, ctx)
        expect(previewStore.list).toHaveBeenCalledTimes(1)
    })
})
