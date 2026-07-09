/**
 * Shared helpers for tests that exercise S3MemoryStore against a real
 * S3-compatible endpoint (SeaweedFS in dev, real S3 in CI when configured).
 *
 * Env conventions match session-replay v2 (SESSION_RECORDING_V2_S3_*):
 *
 *   AGENT_MEMORY_TEST_S3_ENDPOINT       (default http://localhost:8333)
 *   AGENT_MEMORY_TEST_S3_REGION         (default us-east-1)
 *   AGENT_MEMORY_TEST_S3_BUCKET         (default posthog)
 *   AGENT_MEMORY_TEST_S3_ACCESS_KEY_ID  (default any)
 *   AGENT_MEMORY_TEST_S3_SECRET_ACCESS_KEY  (default any)
 *
 * **No skip-if-unreachable.** Memory is core platform machinery; tests fail
 * loudly when the endpoint isn't up so silent regressions can't slip through.
 * Bring up SeaweedFS (hogli start / docker compose up seaweedfs) before
 * running the test suite.
 *
 * Each suite gets its own random prefix under the bucket so concurrent suites
 * don't collide; a teardown helper sweeps that prefix.
 */

import { DeleteObjectsCommand, ListObjectsV2Command, S3Client } from '@aws-sdk/client-s3'
import { randomBytes } from 'node:crypto'

import { S3BundleStore } from '../storage/s3-bundle-store'
import { S3MemoryStore } from './s3-store'

export const TEST_S3_ENDPOINT = process.env.AGENT_MEMORY_TEST_S3_ENDPOINT ?? 'http://localhost:8333'
export const TEST_S3_REGION = process.env.AGENT_MEMORY_TEST_S3_REGION ?? 'us-east-1'
export const TEST_S3_BUCKET = process.env.AGENT_MEMORY_TEST_S3_BUCKET ?? 'posthog'
const TEST_S3_ACCESS_KEY_ID = process.env.AGENT_MEMORY_TEST_S3_ACCESS_KEY_ID ?? 'any'
const TEST_S3_SECRET_ACCESS_KEY = process.env.AGENT_MEMORY_TEST_S3_SECRET_ACCESS_KEY ?? 'any'

export function buildTestS3Client(): S3Client {
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

/** Random per-suite/per-test prefix under the bucket. Keeps concurrent suites isolated. */
export function newTestPrefix(label = 'agent_memory_test'): string {
    return `${label}_${randomBytes(8).toString('hex')}`
}

/**
 * Build a fresh store rooted at a unique prefix. Returned client must be
 * `.destroy()`'d in afterAll; the prefix should be passed to `wipeTestPrefix`
 * in afterAll/afterEach for cleanup.
 */
export function buildTestStore(prefix: string): { client: S3Client; store: S3MemoryStore } {
    const client = buildTestS3Client()
    const store = new S3MemoryStore({ client, bucket: TEST_S3_BUCKET, bucketPrefix: prefix })
    return { client, store }
}

/**
 * S3BundleStore against the same SeaweedFS test bucket, rooted at a per-test
 * prefix. There is no Fs / in-memory bundle store anymore — the harness, every
 * unit test, dev, and prod all go through the real S3 path so the multipart
 * write + signed-URL + listing semantics get exercised.
 */
export function buildTestBundleStore(prefix: string): { client: S3Client; store: S3BundleStore } {
    const client = buildTestS3Client()
    const store = new S3BundleStore({ client, bucket: TEST_S3_BUCKET, bucketPrefix: prefix })
    return { client, store }
}

/** Delete every object under `<prefix>/`. Idempotent. */
export async function wipeTestPrefix(client: S3Client, prefix: string): Promise<void> {
    let continuationToken: string | undefined
    do {
        const list = await client.send(
            new ListObjectsV2Command({
                Bucket: TEST_S3_BUCKET,
                Prefix: `${prefix.replace(/\/+$/, '')}/`,
                ContinuationToken: continuationToken,
            })
        )
        const keys = (list.Contents ?? []).map((o) => ({ Key: o.Key! })).filter((k) => k.Key)
        if (keys.length > 0) {
            await client.send(
                new DeleteObjectsCommand({ Bucket: TEST_S3_BUCKET, Delete: { Objects: keys, Quiet: true } })
            )
        }
        continuationToken = list.IsTruncated ? list.NextContinuationToken : undefined
    } while (continuationToken)
}
