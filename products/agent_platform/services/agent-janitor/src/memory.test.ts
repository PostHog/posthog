/**
 * Janitor /memory/* HTTP routes against real S3 (SeaweedFS in dev).
 *
 * No skip-if-unreachable — memory is core platform infra. Bring up SeaweedFS
 * (`hogli start` / `docker compose up seaweedfs`) before running.
 *
 * Per-suite unique prefix isolates from siblings; afterEach wipes the
 * prefix so individual test cases don't see each other's writes.
 */

import { S3Client } from '@aws-sdk/client-s3'
import { Pool } from 'pg'
import request from 'supertest'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { buildTestStore, newTestPrefix, PgSessionQueue, S3MemoryStore, wipeTestPrefix } from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { buildJanitorApp } from './server'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
let pool: Pool

beforeAll(() => {
    pool = new Pool({ connectionString: TEST_DB_URL })
})

afterAll(async () => {
    await pool.end()
})

beforeEach(async () => {
    await reset({ databaseUrl: TEST_DB_URL })
})

const TEAM = 1
const APP = '019e75de-d9fa-7fe9-a2fb-93a6a545c82b'
const OTHER_APP = '019e7600-0000-7000-8000-000000000000'
const OTHER_TEAM = 99

function mk(memoryStore: S3MemoryStore | undefined): ReturnType<typeof buildJanitorApp> {
    const queue = new PgSessionQueue(pool)
    return buildJanitorApp({
        queue,
        sweep: { queue, stuckRunningThresholdMs: 60_000 },
        memoryStore,
    })
}

describe('janitor /memory/* — store not configured', () => {
    it('every memory route returns 503 when memoryStore is unset', async () => {
        const app = mk(undefined)
        const probes = [
            request(app).get(`/memory/team/${TEAM}/agent/${APP}/files`),
            request(app).get(`/memory/team/${TEAM}/agent/${APP}/files/a.md`),
            request(app).get(`/memory/team/${TEAM}/agent/${APP}/tree`),
            request(app).get(`/memory/team/${TEAM}/agent/${APP}/search`).query({ q: 'x' }),
            request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'x', content: 'y' }),
            request(app).patch(`/memory/team/${TEAM}/agent/${APP}/files/a.md`).send({ description: 'y' }),
            request(app).delete(`/memory/team/${TEAM}/agent/${APP}/files/a.md`),
        ]
        for (const r of probes) {
            const res = await r
            expect(res.status).toBe(503)
            expect(res.body).toEqual({ error: 'memory_store_not_configured' })
        }
    })
})

describe('janitor /memory/* — real S3 / SeaweedFS', () => {
    let client: S3Client
    let store: S3MemoryStore
    let prefix: string
    let app: ReturnType<typeof buildJanitorApp>

    beforeAll(() => {
        prefix = newTestPrefix('agent_memory_janitor_test')
        const built = buildTestStore(prefix)
        client = built.client
        store = built.store
        app = mk(store)
    })

    afterEach(async () => {
        await wipeTestPrefix(client, prefix)
    })

    afterAll(async () => {
        await wipeTestPrefix(client, prefix)
        client.destroy()
    })

    describe('POST /files (create)', () => {
        it('creates a file and stamps created_at + updated_at', async () => {
            const res = await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({
                    path: 'notes/intro.md',
                    description: 'A note',
                    content: 'hello',
                    tags: ['note', 'first'],
                })
            expect(res.status).toBe(201)
            expect(res.body.path).toBe('notes/intro.md')
            expect(typeof res.body.created_at).toBe('string')
            expect(typeof res.body.updated_at).toBe('string')

            // Verify it actually landed in the store (the wire format the
            // runner will see when it hits the same bucket directly).
            const file = await store.read({ teamId: TEAM, applicationId: APP }, 'notes/intro.md')
            expect(file.frontmatter.description).toBe('A note')
            expect(file.frontmatter.tags).toEqual(['note', 'first'])
            expect(file.content).toBe('hello')
        })

        it('returns 409 conflict on duplicate path', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'first', content: 'x' })
                .expect(201)
            const res = await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'second', content: 'y' })
            expect(res.status).toBe(409)
            expect(res.body.error).toBe('conflict')
        })

        it('returns 400 invalid_path for non-conforming paths', async () => {
            const res = await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'UPPER.md', description: 'd', content: 'c' })
            expect(res.status).toBe(400)
            expect(res.body.error).toBe('invalid_path')
        })

        it('returns 400 invalid_frontmatter for over-long description', async () => {
            const res = await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({
                    path: 'b.md',
                    description: 'x'.repeat(500),
                    content: 'c',
                })
            // The Zod request-body validation catches description > 280 first
            // and returns 400 with the ZodError. Either is acceptable as long
            // as the file doesn't land — verify by reading.
            expect(res.status).toBe(400)
            await expect(store.exists({ teamId: TEAM, applicationId: APP }, 'b.md')).resolves.toBe(false)
        })

        it('Zod rejects an empty body with 400', async () => {
            const res = await request(app).post(`/memory/team/${TEAM}/agent/${APP}/files`).send({})
            expect(res.status).toBe(400)
        })
    })

    describe('GET /files (list)', () => {
        it('returns headers under (team, app) only', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'A', content: 'a' })
                .expect(201)
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'incidents/x.md', description: 'AX', content: 'ax' })
                .expect(201)
            // Sibling app + sibling team — must NOT leak into our list.
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${OTHER_APP}/files`)
                .send({ path: 'a.md', description: 'OtherApp', content: 'oa' })
                .expect(201)
            await request(app)
                .post(`/memory/team/${OTHER_TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'OtherTeam', content: 'ot' })
                .expect(201)

            const res = await request(app).get(`/memory/team/${TEAM}/agent/${APP}/files`)
            expect(res.status).toBe(200)
            const paths = (res.body.entries as { path: string }[]).map((e) => e.path).sort()
            expect(paths).toEqual(['a.md', 'incidents/x.md'])
        })

        it('?prefix=incidents/ narrows the list', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'A', content: 'a' })
                .expect(201)
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'incidents/x.md', description: 'AX', content: 'ax' })
                .expect(201)
            const res = await request(app)
                .get(`/memory/team/${TEAM}/agent/${APP}/files`)
                .query({ prefix: 'incidents/' })
            expect((res.body.entries as { path: string }[]).map((e) => e.path)).toEqual(['incidents/x.md'])
        })

        it('returns headers only — bodies are not in the response', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'A', content: 'BODY_A_SHOULD_NOT_APPEAR' })
                .expect(201)
            const res = await request(app).get(`/memory/team/${TEAM}/agent/${APP}/files`)
            expect(JSON.stringify(res.body)).not.toContain('BODY_A_SHOULD_NOT_APPEAR')
        })
    })

    describe('GET /tree', () => {
        it('aggregates files into a folder tree', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'incidents/db.md', description: 'DB', content: 'x' })
                .expect(201)
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'incidents/slack.md', description: 'Slack', content: 'x' })
                .expect(201)
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'runbooks/oncall.md', description: 'OC', content: 'x' })
                .expect(201)

            const res = await request(app).get(`/memory/team/${TEAM}/agent/${APP}/tree`)
            expect(res.status).toBe(200)
            const root = res.body.root as {
                children: { name: string; type: string; children?: { name: string; type: string }[] }[]
            }
            const folderNames = root.children.map((c) => c.name).sort()
            expect(folderNames).toEqual(['incidents', 'runbooks'])
            const incidents = root.children.find((c) => c.name === 'incidents')!
            expect(incidents.type).toBe('folder')
            expect((incidents.children ?? []).map((c) => c.name).sort()).toEqual(['db.md', 'slack.md'])
        })
    })

    describe('GET /files/:path (read)', () => {
        it('returns full body + frontmatter (single-segment path)', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'D', content: 'BODY HERE', tags: ['t1'] })
                .expect(201)

            const res = await request(app).get(`/memory/team/${TEAM}/agent/${APP}/files/a.md`)
            expect(res.status).toBe(200)
            expect(res.body.path).toBe('a.md')
            expect(res.body.description).toBe('D')
            expect(res.body.content).toBe('BODY HERE')
            expect(res.body.tags).toEqual(['t1'])
        })

        it('handles multi-segment paths via the (.*) splat', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'incidents/2026/db.md', description: 'nested', content: 'B' })
                .expect(201)

            const res = await request(app).get(`/memory/team/${TEAM}/agent/${APP}/files/incidents/2026/db.md`)
            expect(res.status).toBe(200)
            expect(res.body.path).toBe('incidents/2026/db.md')
            expect(res.body.content).toBe('B')
        })

        it('returns 404 not_found for missing path', async () => {
            const res = await request(app).get(`/memory/team/${TEAM}/agent/${APP}/files/missing.md`)
            expect(res.status).toBe(404)
            expect(res.body.error).toBe('not_found')
            expect(res.body.path).toBe('missing.md')
        })

        it('returns 400 invalid_path for a malformed path (e.g. uppercase)', async () => {
            const res = await request(app).get(`/memory/team/${TEAM}/agent/${APP}/files/UPPER.md`)
            expect(res.status).toBe(400)
            expect(res.body.error).toBe('invalid_path')
        })
    })

    describe('PATCH /files/:path (update)', () => {
        it('updates only the supplied fields', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'old', content: 'old body', tags: ['kept'] })
                .expect(201)
            const res = await request(app)
                .patch(`/memory/team/${TEAM}/agent/${APP}/files/a.md`)
                .send({ description: 'new' })
            expect(res.status).toBe(200)
            expect(res.body.description).toBe('new')
            // Content + tags preserved
            const file = await store.read({ teamId: TEAM, applicationId: APP }, 'a.md')
            expect(file.content).toBe('old body')
            expect(file.frontmatter.tags).toEqual(['kept'])
        })

        it('updates a nested path', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'incidents/2026/db.md', description: 'd', content: 'old' })
                .expect(201)
            const res = await request(app)
                .patch(`/memory/team/${TEAM}/agent/${APP}/files/incidents/2026/db.md`)
                .send({ content: 'updated body' })
            expect(res.status).toBe(200)
            const file = await store.read({ teamId: TEAM, applicationId: APP }, 'incidents/2026/db.md')
            expect(file.content).toBe('updated body')
        })

        it('returns 404 not_found for missing path', async () => {
            const res = await request(app)
                .patch(`/memory/team/${TEAM}/agent/${APP}/files/nope.md`)
                .send({ description: 'x' })
            expect(res.status).toBe(404)
            expect(res.body.error).toBe('not_found')
        })

        it('returns 400 invalid_frontmatter when patch tags are invalid', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'a.md', description: 'd', content: 'c' })
                .expect(201)
            const res = await request(app)
                .patch(`/memory/team/${TEAM}/agent/${APP}/files/a.md`)
                .send({ tags: ['UPPER'] })
            expect(res.status).toBe(400)
            expect(res.body.error).toBe('invalid_frontmatter')
        })
    })

    describe('DELETE /files/:path', () => {
        it('hard-deletes the file', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({ path: 'gone.md', description: 'bye', content: 'x' })
                .expect(201)
            const res = await request(app).delete(`/memory/team/${TEAM}/agent/${APP}/files/gone.md`)
            expect(res.status).toBe(200)
            expect(res.body.deleted).toBe(true)
            await expect(store.exists({ teamId: TEAM, applicationId: APP }, 'gone.md')).resolves.toBe(false)
        })

        it('returns 404 not_found when the file is missing', async () => {
            const res = await request(app).delete(`/memory/team/${TEAM}/agent/${APP}/files/missing.md`)
            expect(res.status).toBe(404)
            expect(res.body.error).toBe('not_found')
        })
    })

    describe('GET /search', () => {
        it('returns ranked results', async () => {
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({
                    path: 'incidents/db.md',
                    description: 'Postgres pool exhausted',
                    content: 'pgbouncer was undersized',
                    tags: ['db'],
                })
                .expect(201)
            await request(app)
                .post(`/memory/team/${TEAM}/agent/${APP}/files`)
                .send({
                    path: 'notes/unrelated.md',
                    description: 'random thinking',
                    content: 'about pets',
                })
                .expect(201)

            const res = await request(app).get(`/memory/team/${TEAM}/agent/${APP}/search`).query({ q: 'postgres pool' })
            expect(res.status).toBe(200)
            expect(res.body.cue).toBe('postgres pool')
            expect(res.body.count).toBeGreaterThan(0)
            const top = (res.body.results as { path: string }[])[0]
            expect(top.path).toBe('incidents/db.md')
        })

        it('returns 400 when q is missing', async () => {
            const res = await request(app).get(`/memory/team/${TEAM}/agent/${APP}/search`)
            expect(res.status).toBe(400)
        })
    })
})
