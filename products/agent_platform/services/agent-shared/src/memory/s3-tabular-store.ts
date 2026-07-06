/**
 * S3-backed JSONL TabularStore. One object per table; whole-object
 * read-modify-write with ETag optimistic concurrency (mutating ops retry on a
 * 412 so concurrent firings can't lose-update). Talks to real S3 or MinIO.
 */

import {
    DeleteObjectCommand,
    GetObjectCommand,
    ListObjectsV2Command,
    PutObjectCommand,
    S3Client,
} from '@aws-sdk/client-s3'
import { Readable } from 'node:stream'

import { MemoryScope } from './store'
import {
    applyQuery,
    matchRow,
    parseJsonl,
    serializeJsonl,
    TabularConflictError,
    tableKeyFor,
    tablesPrefixFor,
    TableRow,
    TableScalar,
    TabularStore,
    TableQuery,
    MAX_TABLE_BYTES,
    TableTooLargeError,
} from './tabular-store'

export interface S3TabularStoreOpts {
    client: S3Client
    bucket: string
    /** Bucket-level prefix, default `agent_tables`. */
    bucketPrefix?: string
    /** Optimistic-concurrency retry attempts on conditional-write conflict. */
    maxRetries?: number
}

export class S3JsonlTabularStore implements TabularStore {
    private readonly client: S3Client
    private readonly bucket: string
    private readonly bucketPrefix: string
    private readonly maxRetries: number

    constructor(opts: S3TabularStoreOpts) {
        this.client = opts.client
        this.bucket = opts.bucket
        this.bucketPrefix = opts.bucketPrefix ?? 'agent_tables'
        // 20 attempts paired with jittered backoff (see `mutate`) covers the
        // realistic ceiling of concurrent writers per table. Lower numbers
        // exhaust under 10-way contention because lock-step retries keep
        // colliding; the backoff plus headroom is what makes the canary
        // (CONCURRENCY: racing appends) deterministic.
        this.maxRetries = opts.maxRetries ?? 20
    }

    async listTables(scope: MemoryScope): Promise<{ name: string; size: number }[]> {
        const prefix = tablesPrefixFor(scope, this.bucketPrefix)
        const out: { name: string; size: number }[] = []
        let token: string | undefined
        do {
            const res = await this.client.send(
                new ListObjectsV2Command({ Bucket: this.bucket, Prefix: prefix, ContinuationToken: token })
            )
            for (const obj of res.Contents ?? []) {
                if (obj.Key?.endsWith('.jsonl')) {
                    out.push({ name: obj.Key.slice(prefix.length, -'.jsonl'.length), size: obj.Size ?? 0 })
                }
            }
            token = res.IsTruncated ? res.NextContinuationToken : undefined
        } while (token)
        out.sort((a, b) => a.name.localeCompare(b.name))
        return out
    }

    async membership(
        scope: MemoryScope,
        table: string,
        keyColumn: string,
        values: TableScalar[]
    ): Promise<{ known: TableScalar[]; new: TableScalar[] }> {
        const { rows } = await this.readRows(scope, table)
        const present = new Set(rows.map((r) => r[keyColumn] as TableScalar))
        const known: TableScalar[] = []
        const fresh: TableScalar[] = []
        for (const v of values) {
            ;(present.has(v) ? known : fresh).push(v)
        }
        return { known, new: fresh }
    }

    async append(
        scope: MemoryScope,
        table: string,
        rowsToAdd: TableRow[],
        opts: { dedupeOn?: string } = {}
    ): Promise<{ appended: number; skipped: number }> {
        return this.mutate(
            scope,
            table,
            (rows) => {
                let appended = 0
                let skipped = 0
                const seen = opts.dedupeOn ? new Set(rows.map((r) => r[opts.dedupeOn!])) : null
                for (const row of rowsToAdd) {
                    if (seen && row[opts.dedupeOn!] !== undefined && seen.has(row[opts.dedupeOn!])) {
                        skipped++
                        continue
                    }
                    rows.push(row)
                    if (seen) {
                        seen.add(row[opts.dedupeOn!])
                    }
                    appended++
                }
                return { rows, result: { appended, skipped } }
            },
            { checkCeiling: true }
        )
    }

    async query(scope: MemoryScope, table: string, q: TableQuery = {}): Promise<TableRow[]> {
        const { rows } = await this.readRows(scope, table)
        return applyQuery(rows, q)
    }

    async queryPage(
        scope: MemoryScope,
        table: string,
        q: TableQuery = {}
    ): Promise<{ rows: TableRow[]; total: number }> {
        const { rows } = await this.readRows(scope, table)
        return { rows: applyQuery(rows, q), total: rows.length }
    }

    async count(scope: MemoryScope, table: string, where?: TableQuery['where']): Promise<number> {
        const { rows } = await this.readRows(scope, table)
        return rows.filter((r) => matchRow(r, where)).length
    }

    async delete(scope: MemoryScope, table: string, where: TableQuery['where']): Promise<{ deleted: number }> {
        return this.mutate(scope, table, (rows) => {
            const kept = rows.filter((r) => !matchRow(r, where))
            return { rows: kept, result: { deleted: rows.length - kept.length } }
        })
    }

    async truncate(scope: MemoryScope, table: string): Promise<void> {
        const Key = tableKeyFor(scope, table, this.bucketPrefix)
        try {
            await this.client.send(new DeleteObjectCommand({ Bucket: this.bucket, Key }))
        } catch (err) {
            if (!isNotFound(err)) {
                throw err
            }
        }
    }

    // --- internals ---------------------------------------------------------

    private async readRows(scope: MemoryScope, table: string): Promise<{ rows: TableRow[]; etag?: string }> {
        const Key = tableKeyFor(scope, table, this.bucketPrefix)
        try {
            const res = await this.client.send(new GetObjectCommand({ Bucket: this.bucket, Key }))
            return { rows: parseJsonl(await streamToString(res.Body)), etag: res.ETag }
        } catch (err) {
            if (isNotFound(err)) {
                return { rows: [], etag: undefined } // table doesn't exist yet
            }
            throw err
        }
    }

    /** Read-modify-write with ETag optimistic concurrency + bounded retry. */
    private async mutate<R>(
        scope: MemoryScope,
        table: string,
        fn: (rows: TableRow[]) => { rows: TableRow[]; result: R },
        opts: { checkCeiling?: boolean } = {}
    ): Promise<R> {
        const Key = tableKeyFor(scope, table, this.bucketPrefix)
        for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
            const { rows, etag } = await this.readRows(scope, table)
            const { rows: nextRows, result } = fn(rows)
            const body = serializeJsonl(nextRows)
            // Ceiling enforced only on growth paths (append) so a delete can
            // always shrink an over-size table back down.
            if (opts.checkCeiling && Buffer.byteLength(body) > MAX_TABLE_BYTES) {
                throw new TableTooLargeError(table)
            }
            try {
                await this.client.send(
                    new PutObjectCommand({
                        Bucket: this.bucket,
                        Key,
                        Body: body,
                        ContentType: 'application/x-ndjson; charset=utf-8',
                        // Optimistic concurrency: only write if the object is
                        // unchanged since we read it (or still absent on create).
                        ...(etag ? { IfMatch: etag } : { IfNoneMatch: '*' }),
                    })
                )
                return result
            } catch (err) {
                // A real error aborts immediately; a precondition failure means
                // someone else wrote — fall through and retry (re-read, re-apply).
                if (!isPreconditionFailed(err)) {
                    throw err
                }
                // Jittered exponential backoff. Without this, N concurrent
                // writers all retry in lock-step, collide, retry in lock-step
                // again, and exhaust the budget before convergence. Capped at
                // 100ms so a worst-case retry storm finishes inside a single
                // tool call's budget.
                await sleep(jitteredBackoffMs(attempt))
            }
        }
        // Exhausted all retries while still conflicting.
        throw new TabularConflictError(table)
    }
}

function jitteredBackoffMs(attempt: number): number {
    // Minimum 15ms lets SeaweedFS's read-after-write window close before the
    // re-read; without it, retries can see the pre-conflict body and write
    // against a stale ETag that SeaweedFS still accepts. Capped at ~250ms
    // (2^attempt) so a worst-case retry storm finishes inside one tool call.
    const ceiling = Math.min(250, 15 + 2 ** attempt * 5)
    return 15 + Math.floor(Math.random() * (ceiling - 15))
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

async function streamToString(body: unknown): Promise<string> {
    if (!body) {
        return ''
    }
    if (body instanceof Readable) {
        const chunks: Buffer[] = []
        for await (const chunk of body) {
            chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))
        }
        return Buffer.concat(chunks).toString('utf-8')
    }
    const maybe = body as { transformToString?: () => Promise<string> }
    if (typeof maybe.transformToString === 'function') {
        return maybe.transformToString()
    }
    throw new Error('S3JsonlTabularStore: unsupported response body type')
}

function isNotFound(err: unknown): boolean {
    const e = err as { name?: string; $metadata?: { httpStatusCode?: number } }
    return e?.name === 'NoSuchKey' || e?.name === 'NotFound' || e?.$metadata?.httpStatusCode === 404
}

function isPreconditionFailed(err: unknown): boolean {
    const e = err as { name?: string; $metadata?: { httpStatusCode?: number } }
    return e?.name === 'PreconditionFailed' || e?.$metadata?.httpStatusCode === 412
}
