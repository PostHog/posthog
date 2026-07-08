/**
 * Real-S3 (SeaweedFS in dev) tests for S3BundleStore.
 *
 * Mirrors the memory store's test harness: bring up local SeaweedFS via
 * `hogli start` / `docker compose up seaweedfs`, then run the suite.
 * Each test gets its own random prefix so concurrent suites don't collide.
 */

import { DeleteObjectsCommand, ListObjectsV2Command, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { randomBytes } from 'node:crypto'

import { S3BundleStore } from './s3-bundle-store'

const TEST_S3_ENDPOINT = process.env.AGENT_BUNDLE_TEST_S3_ENDPOINT ?? 'http://localhost:8333'
const TEST_S3_REGION = process.env.AGENT_BUNDLE_TEST_S3_REGION ?? 'us-east-1'
const TEST_S3_BUCKET = process.env.AGENT_BUNDLE_TEST_S3_BUCKET ?? 'posthog'
const TEST_S3_ACCESS_KEY_ID = process.env.AGENT_BUNDLE_TEST_S3_ACCESS_KEY_ID ?? 'any'
const TEST_S3_SECRET_ACCESS_KEY = process.env.AGENT_BUNDLE_TEST_S3_SECRET_ACCESS_KEY ?? 'any'

function buildClient(): S3Client {
    return new S3Client({
        endpoint: TEST_S3_ENDPOINT,
        region: TEST_S3_REGION,
        forcePathStyle: true,
        credentials: {
            accessKeyId: TEST_S3_ACCESS_KEY_ID,
            secretAccessKey: TEST_S3_SECRET_ACCESS_KEY,
        },
    })
}

async function wipePrefix(client: S3Client, prefix: string): Promise<void> {
    let continuationToken: string | undefined
    do {
        const list = await client.send(
            new ListObjectsV2Command({
                Bucket: TEST_S3_BUCKET,
                Prefix: prefix,
                ContinuationToken: continuationToken,
            })
        )
        const objects = (list.Contents ?? []).map((o) => ({ Key: o.Key! })).filter((o) => o.Key)
        if (objects.length > 0) {
            await client.send(new DeleteObjectsCommand({ Bucket: TEST_S3_BUCKET, Delete: { Objects: objects } }))
        }
        continuationToken = list.IsTruncated ? list.NextContinuationToken : undefined
    } while (continuationToken)
}

describe('S3BundleStore (real S3 / SeaweedFS)', () => {
    let client: S3Client
    let prefix: string
    let store: S3BundleStore

    beforeEach(() => {
        client = buildClient()
        prefix = `agent_bundles_test_${randomBytes(8).toString('hex')}`
        store = new S3BundleStore({ client, bucket: TEST_S3_BUCKET, bucketPrefix: prefix })
    })

    afterEach(async () => {
        await wipePrefix(client, prefix)
        client.destroy()
    })

    it('writes, reads, and lists files (nested paths)', async () => {
        await store.write('rev1', 'agent.md', '# hello')
        await store.write('rev1', 'skills/research.md', 'be thorough')
        await store.write('rev1', 'tools/x/source.ts', '// x')
        const all = await store.list('rev1')
        expect(all.map((e) => e.path).sort()).toEqual(['agent.md', 'skills/research.md', 'tools/x/source.ts'])
        expect(await store.readText('rev1', 'skills/research.md')).toBe('be thorough')
    })

    it('filters by prefix', async () => {
        await store.write('rev1', 'agent.md', 'x')
        await store.write('rev1', 'skills/a.md', 'x')
        await store.write('rev1', 'skills/b.md', 'x')
        const skills = await store.list('rev1', 'skills/')
        expect(skills.map((e) => e.path).sort()).toEqual(['skills/a.md', 'skills/b.md'])
    })

    it('list returns sha256 written via write', async () => {
        await store.write('rev1', 'agent.md', 'hello')
        const entries = await store.list('rev1')
        expect(entries).toHaveLength(1)
        expect(entries[0].sha256).toMatch(/^[a-f0-9]{64}$/)
        expect(entries[0].size).toBe(5)
    })

    it('freezes and blocks further writes', async () => {
        await store.write('rev1', 'agent.md', 'x')
        const sha = await store.freeze('rev1')
        expect(sha).toMatch(/^[a-f0-9]{64}$/)
        await expect(store.write('rev1', 'agent.md', 'y')).rejects.toThrow(/frozen/)
    })

    it("rejects '..' in paths", async () => {
        await expect(store.write('rev1', '../escape.txt', 'x')).rejects.toThrow(/invalid path/)
    })

    it('delete', async () => {
        await store.write('rev1', 'f.txt', 'x')
        expect(await store.exists('rev1', 'f.txt')).toBe(true)
        await store.delete('rev1', 'f.txt')
        expect(await store.exists('rev1', 'f.txt')).toBe(false)
    })

    it('copy between revisions', async () => {
        await store.write('rev1', 'agent.md', 'shared')
        await store.copy('rev1', 'agent.md', 'rev2', 'agent.md')
        expect(await store.readText('rev2', 'agent.md')).toBe('shared')
    })

    it('produces the same freeze hash across two equivalent revisions', async () => {
        // Same bytes + same paths → identical freeze hash. The bundle store
        // is keyed by (path, sha256), independent of revision id.
        await store.write('a', 'one.md', 'x')
        await store.write('a', 'two.md', 'y')
        const shaA = await store.freeze('a')

        await store.write('b', 'one.md', 'x')
        await store.write('b', 'two.md', 'y')
        const shaB = await store.freeze('b')

        expect(shaA).toBe(shaB)
    })

    it('freeze hash reflects actual bytes, not writer-supplied metadata sha256', async () => {
        // Honest freeze of known content.
        await store.write('clean', 'agent.md', 'hello')
        const cleanSha = await store.freeze('clean')

        // Same bytes, but the object metadata sha256 is tampered to a bogus
        // value (simulating an in-cluster writer setting metadata independently).
        await store.write('tampered', 'agent.md', 'hello')
        await client.send(
            new PutObjectCommand({
                Bucket: TEST_S3_BUCKET,
                Key: `${prefix}/tampered/agent.md`,
                Body: Buffer.from('hello'),
                Metadata: { sha256: 'deadbeef'.repeat(8) },
            })
        )
        // list trusts the (now bogus) metadata...
        expect((await store.list('tampered'))[0].sha256).toBe('deadbeef'.repeat(8))
        // ...but freeze recomputes from bytes, so it matches the honest hash.
        expect(await store.freeze('tampered')).toBe(cleanSha)
    })
})
