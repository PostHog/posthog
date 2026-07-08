/**
 * S3-backed MemoryStore.
 *
 * Talks to a real S3 endpoint OR an S3-compatible local store like SeaweedFS
 * (with `forcePathStyle: true`).
 * Keys live at `<bucketPrefix>/team/<team_id>/agent/<application_slug>/<path>.md`.
 *
 * Why the readHeader Range-GET: `search` ranks across N candidate files but
 * only needs each file's frontmatter to score. A leading 2KB Range-GET is
 * dramatically cheaper than a full GET and captures the YAML block for any
 * reasonably-sized description.
 */

import {
    DeleteObjectCommand,
    GetObjectCommand,
    HeadObjectCommand,
    ListObjectsV2Command,
    PutObjectCommand,
    S3Client,
} from '@aws-sdk/client-s3'
import { Readable } from 'node:stream'

import { parseMemoryDoc, parseMemoryFrontmatter } from './format'
import {
    keyFor,
    MemoryConflictError,
    MemoryFile,
    MemoryHeader,
    MemoryNotFoundError,
    MemoryScope,
    MemoryStore,
    prefixFor,
    PutOpts,
    validateMemoryPath,
} from './store'

/**
 * How many bytes of each candidate file we Range-GET when reading just the
 * frontmatter. 4KB is plenty for the spec's frontmatter fields plus headroom;
 * larger frontmatter blocks just fall back to a full GET (rare in practice).
 */
const HEADER_RANGE_BYTES = 4 * 1024

export interface S3MemoryStoreOpts {
    client: S3Client
    bucket: string
    /** Bucket-level prefix, default `agent_memory`. Trailing/leading slashes are stripped. */
    bucketPrefix?: string
}

export class S3MemoryStore implements MemoryStore {
    private readonly client: S3Client
    private readonly bucket: string
    private readonly bucketPrefix: string

    constructor(opts: S3MemoryStoreOpts) {
        this.client = opts.client
        this.bucket = opts.bucket
        this.bucketPrefix = opts.bucketPrefix ?? 'agent_memory'
    }

    async list(scope: MemoryScope, opts: { prefix?: string } = {}): Promise<MemoryHeader[]> {
        const fullPrefix = prefixFor(scope, this.bucketPrefix, opts.prefix)
        const base = prefixFor(scope, this.bucketPrefix)
        const keys: string[] = []
        let continuationToken: string | undefined
        do {
            const res = await this.client.send(
                new ListObjectsV2Command({
                    Bucket: this.bucket,
                    Prefix: fullPrefix,
                    ContinuationToken: continuationToken,
                })
            )
            for (const obj of res.Contents ?? []) {
                if (obj.Key) {
                    keys.push(obj.Key)
                }
            }
            continuationToken = res.IsTruncated ? res.NextContinuationToken : undefined
        } while (continuationToken)

        // Fetch headers in parallel — small Range-GETs, fan-out keeps it snappy.
        const headers = await Promise.all(
            keys.map(async (key): Promise<MemoryHeader> => {
                const head = await this.rangeGet(key, HEADER_RANGE_BYTES)
                return { path: key.slice(base.length), frontmatter: parseMemoryFrontmatter(head) }
            })
        )
        headers.sort((a, b) => a.path.localeCompare(b.path))
        return headers
    }

    async read(scope: MemoryScope, path: string): Promise<MemoryFile> {
        const key = keyFor(scope, validateMemoryPath(path), this.bucketPrefix)
        const raw = await this.fullGet(key, path)
        const doc = parseMemoryDoc(raw)
        return {
            path,
            frontmatter: {
                description: doc.description,
                tags: doc.tags,
                createdAt: doc.createdAt,
                updatedAt: doc.updatedAt,
            },
            content: doc.content,
        }
    }

    async readHeader(scope: MemoryScope, path: string): Promise<MemoryHeader> {
        const key = keyFor(scope, validateMemoryPath(path), this.bucketPrefix)
        try {
            const raw = await this.rangeGet(key, HEADER_RANGE_BYTES)
            return { path, frontmatter: parseMemoryFrontmatter(raw) }
        } catch (err) {
            if (isNotFound(err)) {
                throw new MemoryNotFoundError(path)
            }
            throw err
        }
    }

    async put(scope: MemoryScope, path: string, raw: string, opts: PutOpts = {}): Promise<void> {
        const key = keyFor(scope, validateMemoryPath(path), this.bucketPrefix)
        if (opts.failIfExists || opts.failIfMissing) {
            const present = await this.head(key)
            if (opts.failIfExists && present) {
                throw new MemoryConflictError(path, 'already exists')
            }
            if (opts.failIfMissing && !present) {
                throw new MemoryNotFoundError(path)
            }
        }
        await this.client.send(
            new PutObjectCommand({
                Bucket: this.bucket,
                Key: key,
                Body: raw,
                ContentType: 'text/markdown; charset=utf-8',
            })
        )
    }

    async delete(scope: MemoryScope, path: string): Promise<void> {
        const key = keyFor(scope, validateMemoryPath(path), this.bucketPrefix)
        if (!(await this.head(key))) {
            throw new MemoryNotFoundError(path)
        }
        await this.client.send(new DeleteObjectCommand({ Bucket: this.bucket, Key: key }))
    }

    async exists(scope: MemoryScope, path: string): Promise<boolean> {
        const key = keyFor(scope, validateMemoryPath(path), this.bucketPrefix)
        return this.head(key)
    }

    private async head(key: string): Promise<boolean> {
        try {
            await this.client.send(new HeadObjectCommand({ Bucket: this.bucket, Key: key }))
            return true
        } catch (err) {
            if (isNotFound(err)) {
                return false
            }
            throw err
        }
    }

    private async rangeGet(key: string, bytes: number): Promise<string> {
        const res = await this.client.send(
            new GetObjectCommand({ Bucket: this.bucket, Key: key, Range: `bytes=0-${bytes - 1}` })
        )
        return streamToString(res.Body)
    }

    private async fullGet(key: string, path: string): Promise<string> {
        try {
            const res = await this.client.send(new GetObjectCommand({ Bucket: this.bucket, Key: key }))
            return streamToString(res.Body)
        } catch (err) {
            if (isNotFound(err)) {
                throw new MemoryNotFoundError(path)
            }
            throw err
        }
    }
}

async function streamToString(body: unknown): Promise<string> {
    if (!body) {
        return ''
    }
    // node:stream Readable in node SDKs; browser ReadableStream would need a
    // different branch, but the runner is node-only.
    if (body instanceof Readable) {
        const chunks: Buffer[] = []
        for await (const chunk of body) {
            chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))
        }
        return Buffer.concat(chunks).toString('utf-8')
    }
    if (typeof (body as { transformToString?: () => Promise<string> }).transformToString === 'function') {
        return await (body as { transformToString: () => Promise<string> }).transformToString()
    }
    throw new Error('S3MemoryStore: unsupported response body type')
}

function isNotFound(err: unknown): boolean {
    const e = err as { name?: string; $metadata?: { httpStatusCode?: number } }
    return e?.name === 'NoSuchKey' || e?.name === 'NotFound' || e?.$metadata?.httpStatusCode === 404
}
