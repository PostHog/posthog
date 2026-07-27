/**
 * Real-S3 (SeaweedFS in dev) tests for S3MemoryStore + searchMemory.
 *
 * No skip-if-unreachable — memory is vital platform infra. Bring up SeaweedFS
 * (`hogli start` / `docker compose up seaweedfs`) before running.
 *
 * Per-suite unique prefix isolates from siblings; afterEach wipes the prefix.
 */

import { S3Client } from '@aws-sdk/client-s3'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { serializeMemoryDoc } from './format'
import { S3MemoryStore } from './s3-store'
import { searchMemory } from './search'
import { keyFor, MemoryConflictError, MemoryNotFoundError, MemoryScope, prefixFor, validateMemoryPath } from './store'
import { buildTestStore, newTestPrefix, wipeTestPrefix } from './test-helpers'

const scopeA: MemoryScope = { teamId: 42, applicationId: 'app-triager' }
const scopeB: MemoryScope = { teamId: 42, applicationId: 'app-resolver' }
const scopeOtherTeam: MemoryScope = { teamId: 99, applicationId: 'app-triager' }

function makeDoc(description: string, content: string, tags: string[] = []): string {
    return serializeMemoryDoc({ description, tags, content })
}

describe('validateMemoryPath', () => {
    it.each([['incidents/2026/db-pool.md'], ['notes.md'], ['a/b/c/d.md'], ['has_underscore-and-dashes.md']])(
        'accepts valid path %s',
        (p) => {
            expect(validateMemoryPath(p)).toBe(p)
        }
    )

    it.each([
        ['/leading-slash.md'],
        ['UPPER.md'],
        ['no-extension'],
        ['../escape.md'],
        ['double//slash.md'],
        ['has space.md'],
        ['has.dots.md'],
    ])('rejects invalid path %s', (p) => {
        expect(() => validateMemoryPath(p)).toThrow()
    })
})

describe('keyFor + prefixFor', () => {
    it('composes the bucket key', () => {
        expect(keyFor(scopeA, 'a/b.md', 'agent_memory')).toBe('agent_memory/team/42/agent/app-triager/a/b.md')
    })

    it('strips slashes from the bucketPrefix', () => {
        expect(keyFor(scopeA, 'x.md', '/agent_memory/')).toBe('agent_memory/team/42/agent/app-triager/x.md')
    })

    it('composes the list prefix', () => {
        expect(prefixFor(scopeA, 'agent_memory')).toBe('agent_memory/team/42/agent/app-triager/')
        expect(prefixFor(scopeA, 'agent_memory', 'incidents/')).toBe(
            'agent_memory/team/42/agent/app-triager/incidents/'
        )
    })

    it('rejects a sub-prefix containing ..', () => {
        expect(() => prefixFor(scopeA, 'agent_memory', '../escape/')).toThrow()
    })
})

describe('S3MemoryStore (real S3 / SeaweedFS)', () => {
    let client: S3Client
    let store: S3MemoryStore
    let prefix: string

    beforeAll(() => {
        prefix = newTestPrefix()
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

    it('write + read round-trips', async () => {
        await store.put(scopeA, 'notes.md', makeDoc('My notes', 'body content'))
        const file = await store.read(scopeA, 'notes.md')
        expect(file.path).toBe('notes.md')
        expect(file.frontmatter.description).toBe('My notes')
        expect(file.content).toBe('body content')
    })

    it('readHeader returns frontmatter only', async () => {
        await store.put(scopeA, 'a.md', makeDoc('description here', 'body', ['tag1']))
        const header = await store.readHeader(scopeA, 'a.md')
        expect(header.path).toBe('a.md')
        expect(header.frontmatter.description).toBe('description here')
        expect(header.frontmatter.tags).toEqual(['tag1'])
    })

    it('list returns headers under (team, app) only', async () => {
        await store.put(scopeA, 'a.md', makeDoc('A', 'a'))
        await store.put(scopeA, 'incidents/x.md', makeDoc('AX', 'ax'))
        await store.put(scopeB, 'a.md', makeDoc('B', 'b')) // different app
        await store.put(scopeOtherTeam, 'a.md', makeDoc('Other', 'o')) // different team

        const listed = await store.list(scopeA)
        expect(listed.map((h) => h.path).sort()).toEqual(['a.md', 'incidents/x.md'])
    })

    it('list with prefix narrows the result', async () => {
        await store.put(scopeA, 'a.md', makeDoc('A', 'a'))
        await store.put(scopeA, 'incidents/x.md', makeDoc('AX', 'ax'))
        await store.put(scopeA, 'incidents/y.md', makeDoc('AY', 'ay'))

        const listed = await store.list(scopeA, { prefix: 'incidents/' })
        expect(listed.map((h) => h.path).sort()).toEqual(['incidents/x.md', 'incidents/y.md'])
    })

    it('put with failIfExists rejects a duplicate', async () => {
        await store.put(scopeA, 'a.md', makeDoc('A', 'a'))
        await expect(store.put(scopeA, 'a.md', makeDoc('A2', 'a2'), { failIfExists: true })).rejects.toBeInstanceOf(
            MemoryConflictError
        )
    })

    it('put with failIfMissing rejects when the file does not exist', async () => {
        await expect(store.put(scopeA, 'a.md', makeDoc('A', 'a'), { failIfMissing: true })).rejects.toBeInstanceOf(
            MemoryNotFoundError
        )
    })

    it('read throws MemoryNotFoundError for missing path', async () => {
        await expect(store.read(scopeA, 'missing.md')).rejects.toBeInstanceOf(MemoryNotFoundError)
    })

    it('delete removes the file', async () => {
        await store.put(scopeA, 'a.md', makeDoc('A', 'a'))
        expect(await store.exists(scopeA, 'a.md')).toBe(true)
        await store.delete(scopeA, 'a.md')
        expect(await store.exists(scopeA, 'a.md')).toBe(false)
    })

    it('delete throws for missing path', async () => {
        await expect(store.delete(scopeA, 'missing.md')).rejects.toBeInstanceOf(MemoryNotFoundError)
    })

    it('cross-team scope isolation: same path in different teams is independent', async () => {
        await store.put(scopeA, 'a.md', makeDoc('TeamA', 'team a body'))
        await store.put(scopeOtherTeam, 'a.md', makeDoc('OtherTeam', 'other team body'))

        const a = await store.read(scopeA, 'a.md')
        const o = await store.read(scopeOtherTeam, 'a.md')
        expect(a.frontmatter.description).toBe('TeamA')
        expect(o.frontmatter.description).toBe('OtherTeam')
    })

    it('cross-app scope isolation within a team', async () => {
        await store.put(scopeA, 'a.md', makeDoc('AppA', 'a'))
        await store.put(scopeB, 'a.md', makeDoc('AppB', 'b'))

        expect((await store.read(scopeA, 'a.md')).frontmatter.description).toBe('AppA')
        expect((await store.read(scopeB, 'a.md')).frontmatter.description).toBe('AppB')

        // App B's list shouldn't see App A's files.
        expect((await store.list(scopeB)).map((h) => h.path)).toEqual(['a.md'])
    })

    it('rejects an invalid path on read/write/delete', async () => {
        await expect(store.put(scopeA, '../escape.md', makeDoc('x', 'y'))).rejects.toThrow()
        await expect(store.read(scopeA, 'UPPER.md')).rejects.toThrow()
        await expect(store.delete(scopeA, '/abs.md')).rejects.toThrow()
    })
})

describe('searchMemory (real S3 / SeaweedFS)', () => {
    let client: S3Client
    let store: S3MemoryStore
    let prefix: string

    beforeAll(() => {
        prefix = newTestPrefix('agent_memory_search_test')
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

    it('ranks a relevant cue above noise', async () => {
        await store.put(
            scopeA,
            'incidents/db-pool.md',
            makeDoc('Postgres connection pool exhausted under traffic', 'pgbouncer default_pool_size was 20', [
                'db',
                'incident',
            ])
        )
        await store.put(
            scopeA,
            'incidents/slack-flood.md',
            makeDoc('Slack alert flood from broken webhook', 'rate limit on channel.search', ['slack', 'incident'])
        )
        await store.put(scopeA, 'notes/random.md', makeDoc('Random thinking', 'body unrelated'))

        const results = await searchMemory(store, scopeA, 'postgres pool exhausted')
        expect(results.length).toBeGreaterThan(0)
        expect(results[0].path).toBe('incidents/db-pool.md')
    })

    it('returns a snippet for the top body match', async () => {
        await store.put(
            scopeA,
            'a.md',
            makeDoc(
                'something',
                'paragraph one talks about pgbouncer connection pools running dry under heavy load conditions and what happened next'
            )
        )
        const results = await searchMemory(store, scopeA, 'pgbouncer connection pool')
        const hit = results.find((r) => r.path === 'a.md')
        expect(hit?.snippet).not.toBeUndefined()
        expect(hit?.snippet).toContain('pgbouncer')
    })

    it('honours a prefix scope', async () => {
        await store.put(scopeA, 'incidents/x.md', makeDoc('Postgres incident', 'body'))
        await store.put(scopeA, 'runbooks/x.md', makeDoc('Postgres runbook', 'body'))

        const results = await searchMemory(store, scopeA, 'postgres', { prefix: 'incidents/' })
        expect(results.map((r) => r.path)).toEqual(['incidents/x.md'])
    })
})
