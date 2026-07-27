/**
 * S3-backed BundleStore. Each revision is a key prefix under `<bucketPrefix>/`;
 * each file in the bundle is a separate S3 object. Frozen revisions get a
 * `.frozen` marker object (mirrors FsBundleStore) and subsequent writes throw.
 *
 * sha256 is stored as object metadata on `write` so `list` doesn't need to
 * fetch each object body. `freeze` hashes the (path, sha256) tuples in path
 * order — identical layout to FsBundleStore so the same revision bytes
 * produce the same frozen hash regardless of backend.
 */

import {
    CopyObjectCommand,
    DeleteObjectCommand,
    GetObjectCommand,
    HeadObjectCommand,
    ListObjectsV2Command,
    PutObjectCommand,
    S3Client,
    S3ServiceException,
} from '@aws-sdk/client-s3'
import { createHash } from 'crypto'
import { Readable } from 'node:stream'

import { BundleEntry, BundleStore } from './bundle'

const FROZEN_MARKER = '.frozen'

export interface S3BundleStoreOpts {
    client: S3Client
    bucket: string
    /** Bucket-level prefix, default `agent_bundles`. Trailing/leading slashes are stripped. */
    bucketPrefix?: string
}

export class S3BundleStore implements BundleStore {
    private readonly client: S3Client
    private readonly bucket: string
    private readonly bucketPrefix: string

    constructor(opts: S3BundleStoreOpts) {
        this.client = opts.client
        this.bucket = opts.bucket
        this.bucketPrefix = (opts.bucketPrefix ?? 'agent_bundles').replace(/^\/+|\/+$/g, '')
    }

    private revPrefix(rev: string): string {
        return `${this.bucketPrefix}/${rev}/`
    }

    private keyFor(rev: string, p: string): string {
        if (p.includes('..')) {
            throw new Error(`invalid path: ${p}`)
        }
        return `${this.revPrefix(rev)}${p}`
    }

    async isFrozen(rev: string): Promise<boolean> {
        return this.headObject(this.keyFor(rev, FROZEN_MARKER))
    }

    async list(rev: string, prefix?: string): Promise<BundleEntry[]> {
        const base = this.revPrefix(rev)
        const fullPrefix = prefix ? `${base}${prefix}` : base
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
                if (obj.Key && !obj.Key.endsWith(`/${FROZEN_MARKER}`)) {
                    keys.push(obj.Key)
                }
            }
            continuationToken = res.IsTruncated ? res.NextContinuationToken : undefined
        } while (continuationToken)

        const entries = await Promise.all(
            keys.map(async (key): Promise<BundleEntry> => {
                const head = await this.client.send(new HeadObjectCommand({ Bucket: this.bucket, Key: key }))
                const sha = head.Metadata?.sha256 ?? ''
                return {
                    path: key.slice(base.length),
                    size: head.ContentLength ?? 0,
                    sha256: sha,
                }
            })
        )
        entries.sort((a, b) => a.path.localeCompare(b.path))
        return entries
    }

    async read(rev: string, p: string): Promise<Buffer> {
        const res = await this.client.send(new GetObjectCommand({ Bucket: this.bucket, Key: this.keyFor(rev, p) }))
        return streamToBuffer(res.Body as Readable)
    }

    async readText(rev: string, p: string): Promise<string> {
        return (await this.read(rev, p)).toString('utf-8')
    }

    async write(rev: string, p: string, content: Buffer | string): Promise<void> {
        if (await this.isFrozen(rev)) {
            throw new Error(`bundle ${rev} is frozen`)
        }
        const buf = typeof content === 'string' ? Buffer.from(content, 'utf-8') : content
        const sha256 = createHash('sha256').update(buf).digest('hex')
        await this.client.send(
            new PutObjectCommand({
                Bucket: this.bucket,
                Key: this.keyFor(rev, p),
                Body: buf,
                Metadata: { sha256 },
            })
        )
    }

    async delete(rev: string, p: string): Promise<void> {
        if (await this.isFrozen(rev)) {
            throw new Error(`bundle ${rev} is frozen`)
        }
        await this.client.send(new DeleteObjectCommand({ Bucket: this.bucket, Key: this.keyFor(rev, p) }))
    }

    async exists(rev: string, p: string): Promise<boolean> {
        return this.headObject(this.keyFor(rev, p))
    }

    async freeze(rev: string, precomputedEntries?: BundleEntry[]): Promise<string> {
        const listed = precomputedEntries ?? (await this.list(rev))
        // Recompute each file's sha256 from its actual bytes rather than trusting
        // the writer-supplied object metadata `list` reads. The freeze hash is the
        // bundle's integrity anchor, so it must reflect content, not a metadata
        // field an in-cluster writer could set independently. For honestly-written
        // objects this equals the metadata hash, so the frozen hash is unchanged.
        const verified = await Promise.all(
            listed.map(async (e): Promise<BundleEntry> => ({ ...e, sha256: await this.sha256OfObject(rev, e.path) }))
        )
        verified.sort((a, b) => a.path.localeCompare(b.path))
        const hash = createHash('sha256')
        for (const e of verified) {
            hash.update(e.path).update('\0').update(e.sha256).update('\0')
        }
        const sha = hash.digest('hex')
        await this.client.send(
            new PutObjectCommand({
                Bucket: this.bucket,
                Key: this.keyFor(rev, FROZEN_MARKER),
                Body: sha,
            })
        )
        return sha
    }

    async copy(srcRev: string, srcPath: string, dstRev: string, dstPath: string): Promise<void> {
        // S3-side copy avoids streaming bytes through this process. CopySource
        // uses URL-encoded bucket/key per AWS conventions.
        const srcKey = this.keyFor(srcRev, srcPath)
        await this.client.send(
            new CopyObjectCommand({
                Bucket: this.bucket,
                Key: this.keyFor(dstRev, dstPath),
                CopySource: `/${this.bucket}/${encodeURIComponent(srcKey)}`,
                MetadataDirective: 'COPY',
            })
        )
    }

    /** sha256 hex of an object's actual bytes — used to verify integrity at freeze. */
    private async sha256OfObject(rev: string, p: string): Promise<string> {
        const buf = await this.read(rev, p)
        return createHash('sha256').update(buf).digest('hex')
    }

    private async headObject(key: string): Promise<boolean> {
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
}

function isNotFound(err: unknown): boolean {
    if (err instanceof S3ServiceException) {
        return err.$metadata?.httpStatusCode === 404 || err.name === 'NotFound' || err.name === 'NoSuchKey'
    }
    return false
}

async function streamToBuffer(stream: Readable): Promise<Buffer> {
    const chunks: Buffer[] = []
    for await (const chunk of stream) {
        chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))
    }
    return Buffer.concat(chunks)
}
