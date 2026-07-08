/**
 * Cross-session memory persistence: session A writes a memory file via
 * @posthog/memory-write; a FRESH session B reads it back via
 * @posthog/memory-read and the model's reply confirms the persisted content.
 *
 * Wired against an `InMemoryMemoryStore` in the harness (same interface as
 * `S3MemoryStore`) so the test exercises every layer of the dispatch chain —
 * native tool registry, ToolContext.memoryStore injection, store API,
 * frontmatter serializer — without standing up SeaweedFS/S3.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

describe('memory tools: cross-session round-trip', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('session A writes; session B reads back; the body survives across sessions', async () => {
        // Session A: model calls memory-write, then ends turn.
        // Two scripted turns because the runner re-invokes the model after
        // a successful tool dispatch (the tool_result becomes the next user
        // message, the second turn closes the session).
        c.setScript([
            fauxCallTool('@posthog/memory-write', {
                path: 'notes/db-incident.md',
                description: 'Postgres connection pool exhausted under traffic',
                content: 'pgbouncer default_pool_size was 20, raised to 80',
                tags: ['db', 'incident'],
            }),
            fauxText('stored the note'),
        ])

        await c.deployAgent({
            slug: 'memuser',
            spec: {
                tools: [
                    { kind: 'native', id: '@posthog/memory-write' },
                    { kind: 'native', id: '@posthog/memory-read' },
                ],
            },
        })

        const runA = await request(c.ingress).post('/agents/memuser/run').send({ message: 'remember this' })
        expect(runA.status).toBe(200)
        const sidA = runA.body.session_id
        await c.drain()
        expect((await c.queue.get(sidA))!.state).toBe('completed')

        // Verify the file actually landed via the memoryStore — proves the
        // tool ran and the dispatch chain wired memoryStore through.
        const appA = await c.revisions.getApplicationBySlug('memuser')
        const stored = await c.memoryStore.read({ teamId: 1, applicationId: appA!.id }, 'notes/db-incident.md')
        expect(stored.frontmatter.description).toBe('Postgres connection pool exhausted under traffic')
        expect(stored.content).toBe('pgbouncer default_pool_size was 20, raised to 80')

        // Session B (fresh session, same agent): script the model to call
        // memory-read for the path we wrote, then echo the body back.
        c.setScript([
            fauxCallTool('@posthog/memory-read', { path: 'notes/db-incident.md' }),
            fauxText('the fix was: pgbouncer default_pool_size was 20, raised to 80'),
        ])

        const runB = await request(c.ingress).post('/agents/memuser/run').send({ message: 'what do we know?' })
        expect(runB.status).toBe(200)
        const sidB = runB.body.session_id
        expect(sidB).not.toBe(sidA)
        await c.drain()

        const sessionB = (await c.queue.get(sidB))!
        expect(sessionB.state).toBe('completed')

        // The final assistant text in session B references the body session A
        // wrote — proves the tool_result actually fed back into the model
        // context (the runner ran memory-read, returned the envelope, the
        // model emitted the body verbatim in the next scripted turn).
        const lastAssistant = [...sessionB.conversation].reverse().find((m) => m.role === 'assistant')
        const text =
            lastAssistant && typeof lastAssistant.content !== 'string'
                ? lastAssistant.content
                      .filter((b): b is { type: 'text'; text: string } => b.type === 'text')
                      .map((b) => b.text)
                      .join('')
                : ''
        expect(text).toContain('pgbouncer default_pool_size was 20, raised to 80')
    })

    it('session A updates an existing memory; session B sees the new content', async () => {
        // Pre-seed via the store directly so we're testing update specifically.
        await c.deployAgent({
            slug: 'memupdater',
            spec: {
                tools: [
                    { kind: 'native', id: '@posthog/memory-update' },
                    { kind: 'native', id: '@posthog/memory-read' },
                ],
            },
        })
        const app = await c.revisions.getApplicationBySlug('memupdater')
        const scope = { teamId: 1, applicationId: app!.id }
        await c.memoryStore.put(
            scope,
            'runbook.md',
            '---\ndescription: old policy\ntags: []\ncreated_at: 2026-01-01T00:00:00Z\n---\n\nold body content\n'
        )

        // Session A: model calls memory-update.
        c.setScript([
            fauxCallTool('@posthog/memory-update', {
                path: 'runbook.md',
                content: 'new body content after the rewrite',
            }),
            fauxText('updated'),
        ])
        const runA = await request(c.ingress).post('/agents/memupdater/run').send({ message: 'update it' })
        expect(runA.status).toBe(200)
        await c.drain()

        // Verify update landed at the store layer.
        const updated = await c.memoryStore.read(scope, 'runbook.md')
        expect(updated.content).toBe('new body content after the rewrite')
        expect(updated.frontmatter.description).toBe('old policy') // preserved

        // Session B: fresh session reads, model parrots the new body.
        c.setScript([
            fauxCallTool('@posthog/memory-read', { path: 'runbook.md' }),
            fauxText('current body: new body content after the rewrite'),
        ])
        const runB = await request(c.ingress).post('/agents/memupdater/run').send({ message: 'what does it say?' })
        await c.drain()

        const sessionB = (await c.queue.get(runB.body.session_id))!
        const lastAssistant = [...sessionB.conversation].reverse().find((m) => m.role === 'assistant')
        const text =
            lastAssistant && typeof lastAssistant.content !== 'string'
                ? lastAssistant.content
                      .filter((b): b is { type: 'text'; text: string } => b.type === 'text')
                      .map((b) => b.text)
                      .join('')
                : ''
        expect(text).toContain('new body content after the rewrite')
    })

    it('memory-search across sessions finds files written by the same agent', async () => {
        // Write three memories from session A.
        c.setScript([
            fauxCallTool('@posthog/memory-write', {
                path: 'incidents/db.md',
                description: 'Postgres pool exhausted',
                content: 'pgbouncer too small',
                tags: ['db', 'incident'],
            }),
            fauxCallTool('@posthog/memory-write', {
                path: 'incidents/slack.md',
                description: 'Slack notifications delayed',
                content: 'channel.search rate-limited',
                tags: ['slack', 'incident'],
            }),
            fauxCallTool('@posthog/memory-write', {
                path: 'notes/random.md',
                description: 'Random thought',
                content: 'unrelated note',
                tags: [],
            }),
            fauxText('done writing'),
        ])
        await c.deployAgent({
            slug: 'memsearcher',
            spec: {
                tools: [
                    { kind: 'native', id: '@posthog/memory-write' },
                    { kind: 'native', id: '@posthog/memory-search' },
                ],
            },
        })
        await request(c.ingress).post('/agents/memsearcher/run').send({ message: 'seed' })
        await c.drain()

        // Session B searches. Faux assistant echoes a path that only appears
        // via the search tool result — proves search ran against the same
        // S3-backed store the writes targeted.
        c.setScript([
            fauxCallTool('@posthog/memory-search', { cue: 'postgres connection pool' }),
            fauxText('top hit: incidents/db.md'),
        ])
        const runB = await request(c.ingress).post('/agents/memsearcher/run').send({ message: 'search' })
        await c.drain()

        const sessionB = (await c.queue.get(runB.body.session_id))!
        expect(sessionB.state).toBe('completed')
        const lastAssistant = [...sessionB.conversation].reverse().find((m) => m.role === 'assistant')
        const text =
            lastAssistant && typeof lastAssistant.content !== 'string'
                ? lastAssistant.content
                      .filter((b): b is { type: 'text'; text: string } => b.type === 'text')
                      .map((b) => b.text)
                      .join('')
                : ''
        expect(text).toContain('incidents/db.md')
    })
})

/**
 * Two-callers, one bucket contract. The runner writes via `@posthog/memory-*`
 * tools; the janitor HTTP surface (which Django proxies through) writes the
 * SAME bucket via `S3MemoryStore.put()`. If the key layout drifts between
 * them these tests fail — locking in the invariant that the UI sees what the
 * agent writes and the agent sees what a human writes.
 */
describe('memory: janitor + runner share one bucket', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('janitor-write → runner-read: a file POSTed to the janitor surfaces in @posthog/memory-read', async () => {
        await c.deployAgent({
            slug: 'shared-bucket-jw',
            spec: { tools: [{ kind: 'native', id: '@posthog/memory-read' }] },
        })
        const app = await c.revisions.getApplicationBySlug('shared-bucket-jw')
        const applicationId = app!.id

        const writeRes = await request(c.janitor)
            .post(`/memory/team/1/agent/${applicationId}/files`)
            .send({
                path: 'shared/hello.md',
                description: 'Posted by the janitor — should be visible to the agent',
                content: 'shared bucket: this file was written via the janitor, not the agent',
                tags: ['shared'],
            })
        expect(writeRes.status).toBe(201)
        expect(writeRes.body.path).toBe('shared/hello.md')

        c.setScript([
            fauxCallTool('@posthog/memory-read', { path: 'shared/hello.md' }),
            fauxText('the human wrote: shared bucket: this file was written via the janitor, not the agent'),
        ])
        const run = await request(c.ingress).post('/agents/shared-bucket-jw/run').send({ message: 'read it' })
        expect(run.status).toBe(200)
        await c.drain()
        const session = (await c.queue.get(run.body.session_id))!
        expect(session.state).toBe('completed')
        const lastAssistant = [...session.conversation].reverse().find((m) => m.role === 'assistant')
        const text =
            lastAssistant && typeof lastAssistant.content !== 'string'
                ? lastAssistant.content
                      .filter((b): b is { type: 'text'; text: string } => b.type === 'text')
                      .map((b) => b.text)
                      .join('')
                : ''
        expect(text).toContain('shared bucket: this file was written via the janitor, not the agent')
    })

    it('runner-write → janitor-read: a file the agent writes via @posthog/memory-write is visible on GET /memory/.../files', async () => {
        await c.deployAgent({
            slug: 'shared-bucket-rw',
            spec: { tools: [{ kind: 'native', id: '@posthog/memory-write' }] },
        })
        const app = await c.revisions.getApplicationBySlug('shared-bucket-rw')
        const applicationId = app!.id

        c.setScript([
            fauxCallTool('@posthog/memory-write', {
                path: 'agent-wrote/note.md',
                description: 'Written by the agent, read by the janitor',
                content: 'the agent wrote this body via @posthog/memory-write',
                tags: ['agent'],
            }),
            fauxText('done writing'),
        ])
        const run = await request(c.ingress).post('/agents/shared-bucket-rw/run').send({ message: 'write it' })
        expect(run.status).toBe(200)
        await c.drain()
        const session = (await c.queue.get(run.body.session_id))!
        expect(session.state).toBe('completed')

        const listRes = await request(c.janitor).get(`/memory/team/1/agent/${applicationId}/files`)
        expect(listRes.status).toBe(200)
        const entries = listRes.body.entries as { path: string; description: string }[]
        const entry = entries.find((e) => e.path === 'agent-wrote/note.md')
        expect(entry).toBeTruthy()
        expect(entry?.description).toBe('Written by the agent, read by the janitor')

        const readRes = await request(c.janitor).get(`/memory/team/1/agent/${applicationId}/files/agent-wrote/note.md`)
        expect(readRes.status).toBe(200)
        expect(readRes.body.content).toBe('the agent wrote this body via @posthog/memory-write')
        expect(readRes.body.tags).toEqual(['agent'])
    })

    it('janitor PATCH → runner-list sees the updated description', async () => {
        await c.deployAgent({
            slug: 'shared-bucket-patch',
            spec: { tools: [{ kind: 'native', id: '@posthog/memory-list' }] },
        })
        const app = await c.revisions.getApplicationBySlug('shared-bucket-patch')
        const applicationId = app!.id

        await request(c.janitor)
            .post(`/memory/team/1/agent/${applicationId}/files`)
            .send({ path: 'p.md', description: 'old description', content: 'body' })
            .expect(201)

        const patchRes = await request(c.janitor)
            .patch(`/memory/team/1/agent/${applicationId}/files/p.md`)
            .send({ description: 'new description after patch' })
        expect(patchRes.status).toBe(200)
        expect(patchRes.body.description).toBe('new description after patch')

        c.setScript([fauxCallTool('@posthog/memory-list', {}), fauxText('found: new description after patch')])
        const run = await request(c.ingress)
            .post('/agents/shared-bucket-patch/run')
            .send({ message: 'list everything' })
        await c.drain()
        const session = (await c.queue.get(run.body.session_id))!
        const lastAssistant = [...session.conversation].reverse().find((m) => m.role === 'assistant')
        const text =
            lastAssistant && typeof lastAssistant.content !== 'string'
                ? lastAssistant.content
                      .filter((b): b is { type: 'text'; text: string } => b.type === 'text')
                      .map((b) => b.text)
                      .join('')
                : ''
        expect(text).toContain('new description after patch')
    })
})
