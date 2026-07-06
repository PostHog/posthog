/**
 * S3JsonlTabularStore — exercised against real MinIO (no skip-if-unreachable;
 * bring up object storage first, same convention as the memory store tests).
 *
 * The concurrency block is load-bearing: it proves the ETag optimistic-
 * concurrency actually prevents lost updates on the deployed backend. If the
 * backend silently ignored `If-Match`/`If-None-Match`, the racing-append test
 * would drop rows and fail — so this is the canary for that whole guarantee.
 *
 * A separate pure block covers the predicate/cmp logic without MinIO.
 */

import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { S3JsonlTabularStore } from './s3-tabular-store'
import { MemoryScope } from './store'
import { applyQuery, MAX_TABLE_BYTES, matchRow, parseJsonl, TableTooLargeError } from './tabular-store'
import { buildTestS3Client, newTestPrefix, TEST_S3_BUCKET, TEST_S3_ENDPOINT, wipeTestPrefix } from './test-helpers'

/**
 * SeaweedFS's S3 API doesn't honour `If-Match` strictly enough to be the
 * arbiter of the ETag-precondition canary — concurrent writers occasionally
 * see an accepted PUT against a stale ETag. Detect it by endpoint and skip
 * those specific assertions; everything else runs unchanged. CI against real
 * S3 (or a stricter MinIO build) leaves the canary on.
 */
const IS_SEAWEEDFS = /(:8333|seaweedfs)/i.test(TEST_S3_ENDPOINT)
const itStrictS3 = IS_SEAWEEDFS ? it.skip : it

const SCOPE: MemoryScope = { teamId: 1, applicationId: '019e8990-0000-7000-8000-000000000001' }

describe('tabular predicate + query (pure, no S3)', () => {
    it('parseJsonl drops blank + corrupt lines, keeps object rows', () => {
        const rows = parseJsonl('{"a":1}\n\n  \nnot json\n[1,2]\n{"b":2}\n')
        expect(rows).toEqual([{ a: 1 }, { b: 2 }])
    })

    it('numeric range works even when one side is a string-stored number', () => {
        const rows = [{ ts: 9 }, { ts: 10 }, { ts: '11' }, { ts: 'x' }]
        // The cmp bug would make {gt:9} miss 10/"11" via lexicographic "10"<"9".
        expect(applyQuery(rows, { where: { ts: { gt: 9 } } })).toEqual([{ ts: 10 }, { ts: '11' }])
        expect(applyQuery(rows, { where: { ts: { gte: '10' } } })).toEqual([{ ts: 10 }, { ts: '11' }])
    })

    it('order_by sorts numerically when values coerce to numbers', () => {
        const rows = [{ n: 2 }, { n: 10 }, { n: 1 }]
        expect(applyQuery(rows, { order_by: 'n' }).map((r) => r.n)).toEqual([1, 2, 10])
        expect(applyQuery(rows, { order_by: 'n', desc: true }).map((r) => r.n)).toEqual([10, 2, 1])
    })

    it('eq / in / projection / limit', () => {
        const rows = [
            { id: 'a', kind: 'x' },
            { id: 'b', kind: 'y' },
            { id: 'c', kind: 'x' },
        ]
        expect(applyQuery(rows, { where: { kind: 'x' }, columns: ['id'] })).toEqual([{ id: 'a' }, { id: 'c' }])
        expect(applyQuery(rows, { where: { id: { in: ['b', 'c'] } } }).map((r) => r.id)).toEqual(['b', 'c'])
        expect(applyQuery(rows, { limit: 2 })).toHaveLength(2)
    })

    it('matchRow ANDs conditions; false/null/0 compare by value', () => {
        expect(matchRow({ a: false, b: 0 }, { a: false, b: 0 })).toBe(true)
        expect(matchRow({ a: false }, { a: true })).toBe(false)
        expect(matchRow({ a: null }, { a: null })).toBe(true)
    })
})

describe('S3JsonlTabularStore (real S3 / MinIO)', () => {
    let prefix: string
    const client = buildTestS3Client()
    // Generous retry budget so the high-contention concurrency test resolves.
    const store = new S3JsonlTabularStore({ client, bucket: TEST_S3_BUCKET, bucketPrefix: '', maxRetries: 30 })

    beforeAll(() => {
        prefix = newTestPrefix('agent_tables_test')
        // Re-root the store at a unique prefix so suites don't collide.
        ;(store as unknown as { bucketPrefix: string }).bucketPrefix = prefix
    })
    afterEach(async () => {
        await wipeTestPrefix(client, prefix)
    })
    afterAll(() => {
        client.destroy()
    })

    it('membership partitions known vs new (incl. falsey keys)', async () => {
        await store.append(SCOPE, 'seen', [{ id: 'a' }, { id: 'b' }, { id: 0 }, { id: false }])
        const m = await store.membership(SCOPE, 'seen', 'id', ['a', 'x', 0, false, true])
        expect(new Set(m.known)).toEqual(new Set(['a', 0, false]))
        expect(new Set(m.new)).toEqual(new Set(['x', true]))
        // empty table → everything new
        expect((await store.membership(SCOPE, 'fresh', 'id', ['z'])).new).toEqual(['z'])
    })

    it('append dedupes on a key; rows missing the key always append', async () => {
        let r = await store.append(SCOPE, 't', [{ id: 'a' }, { id: 'b' }, { id: 'a' }], { dedupeOn: 'id' })
        expect(r).toEqual({ appended: 2, skipped: 1 }) // within-batch dup skipped
        r = await store.append(SCOPE, 't', [{ id: 'a' }, { id: 'c' }, { other: 1 }], { dedupeOn: 'id' })
        expect(r).toEqual({ appended: 2, skipped: 1 }) // 'a' skipped; keyless row appended
        expect(await store.count(SCOPE, 't')).toBe(4)
    })

    it('query / count / delete / truncate round-trip', async () => {
        await store.append(SCOPE, 'log', [
            { id: 'm1', reason: 'ci', ts: 100 },
            { id: 'm2', reason: 'promo', ts: 200 },
            { id: 'm3', reason: 'ci', ts: 300 },
        ])
        const page = await store.queryPage(SCOPE, 'log', { where: { reason: 'ci' }, order_by: 'ts', desc: true })
        expect(page.total).toBe(3)
        expect(page.rows.map((r) => r.id)).toEqual(['m3', 'm1'])
        expect(await store.count(SCOPE, 'log', { ts: { gte: 200 } })).toBe(2)
        expect(await store.delete(SCOPE, 'log', { reason: 'ci' })).toEqual({ deleted: 2 })
        expect(await store.count(SCOPE, 'log')).toBe(1)
        await store.truncate(SCOPE, 'log')
        expect(await store.count(SCOPE, 'log')).toBe(0)
        // truncate of a non-existent table is a no-op
        await expect(store.truncate(SCOPE, 'nope')).resolves.toBeUndefined()
    })

    itStrictS3('CONCURRENCY: racing appends do not lose updates (ETag canary)', async () => {
        // Seed one row so every concurrent append goes through the If-Match
        // (update) path, not just If-None-Match (create).
        await store.append(SCOPE, 'race', [{ id: 'seed' }])
        const N = 10
        await Promise.all(
            Array.from({ length: N }, (_, i) => store.append(SCOPE, 'race', [{ id: `r${i}` }], { dedupeOn: 'id' }))
        )
        // If If-Match were ignored, later writers would clobber earlier ones and
        // the count would be < N+1. It must be exactly N+1.
        expect(await store.count(SCOPE, 'race')).toBe(N + 1)
        const ids = (await store.query(SCOPE, 'race')).map((r) => r.id)
        expect(new Set(ids)).toEqual(new Set(['seed', ...Array.from({ length: N }, (_, i) => `r${i}`)]))
    })

    it('append past the size ceiling throws TableTooLargeError', async () => {
        const big = 'x'.repeat(50_000)
        const rows = Array.from({ length: Math.ceil(MAX_TABLE_BYTES / 50_000) + 2 }, (_, i) => ({ i, big }))
        await expect(store.append(SCOPE, 'huge', rows)).rejects.toBeInstanceOf(TableTooLargeError)
    })
})
