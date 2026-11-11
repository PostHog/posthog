import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseJsonOrUndefined } from '@/core/json'
import type { Runtime } from '@/core/runtime'
import { failWith, parseOrThrow, type Schema } from '@/core/schema'
import { sendRequest } from '@/posthog/api'
import { hostUrl } from '@/posthog/host'
import type { KeySession } from '@/posthog/key-session'

import { contentHash } from './container'

// The symbol set upload protocol of posthog-cli (`api/symbol_sets.rs`). Bodies, endpoints, retry
// counts and the release-mismatch fallback match it, so PostHog sees the same requests from either
// CLI. Only the user agent differs.

export interface SymbolSetUpload {
    chunkId: string
    releaseId: string | null
    data: Uint8Array
    // Set when the hash covers something other than the whole container, like event-mode sourcemaps.
    contentHash?: string
}

export type UploadStatus = 'uploaded' | 'already_present' | 'too_large'

export interface UploadOptions {
    batchSize: number
    force: boolean
    skipOnConflict: boolean
    concurrency?: number
    // Filled as chunks finish, so a caller still sees what a failed run uploaded.
    progress?: Map<string, UploadStatus>
}

export interface UploadOutcome {
    status: Map<string, UploadStatus>
    contentHashes: Map<string, string>
}

export const MAX_FILE_SIZE = 100 * 1024 * 1024
const CHECK_BATCH_SIZE = 1000
const REQUEST_TIMEOUT_MS = 30_000
// A symbol set can be 100 MB. Its deadline grows with its size, so only a link slower than this fails.
const MIN_TRANSFER_BYTES_PER_SECOND = 50_000

function transferTimeout(bytes: number): number {
    return REQUEST_TIMEOUT_MS + Math.ceil((bytes / MIN_TRANSFER_BYTES_PER_SECOND) * 1000)
}
const RATE_LIMIT_PER_MINUTE = 480

const ErrorBody = z.object({ code: z.string() })

export function errorCode(body: string): string | undefined {
    return parseJsonOrUndefined(body, ErrorBody)?.code
}

class ApiFailure extends Error {
    constructor(
        readonly status: number,
        readonly body: string,
        readonly url: string
    ) {
        super(`PostHog answered ${status} for ${url}: ${body}`)
    }

    // posthog-cli matches error codes in the parsed body, or anywhere in the raw text as a fallback.
    hasCode(code: string): boolean {
        return errorCode(this.body) === code || this.body.includes(code)
    }
}

class ReleaseIdMismatch extends Error {}

// A sliding window of request times over the last minute, like posthog-cli's throttler.
class Throttle {
    private readonly times: number[] = []

    constructor(
        private readonly runtime: Runtime,
        private readonly perMinute: number
    ) {}

    async wait(): Promise<void> {
        if (this.times.length >= this.perMinute) {
            const oldest = this.times.shift()!
            const delay = oldest + 60_000 - this.runtime.now()
            if (delay > 0) {
                await this.runtime.sleep(delay)
            }
        }
        this.times.push(this.runtime.now())
    }
}

// `retry_policy(500, 2, n)`: n attempts, sleeping 500 ms, then 1 s, then 2 s between them.
async function withRetries<T>(
    runtime: Runtime,
    attempts: number,
    action: (attempt: number) => Promise<T>,
    shouldRetry: (error: unknown) => boolean = () => true
): Promise<T> {
    for (let attempt = 0; ; attempt++) {
        try {
            return await action(attempt)
        } catch (error) {
            if (attempt + 1 >= attempts || !shouldRetry(error)) {
                throw error
            }
            await runtime.sleep(500 * 2 ** attempt)
        }
    }
}

// UUIDv7 as uuid's `now_v7`: 48-bit millisecond timestamp, version 7, variant 10, random rest.
export function uuidv7(now: number): string {
    const bytes = crypto.getRandomValues(new Uint8Array(16))
    const time = BigInt(now)
    for (let index = 0; index < 6; index++) {
        bytes[index] = Number((time >> BigInt(8 * (5 - index))) & 0xffn)
    }
    bytes[6] = (bytes[6]! & 0x0f) | 0x70
    bytes[8] = (bytes[8]! & 0x3f) | 0x80
    const hex = Buffer.from(bytes).toString('hex')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

const PresignedPost = z.object({ url: z.string(), fields: z.record(z.string(), z.string()) })

type PresignedPost = z.output<typeof PresignedPost>

const StartEntry = z.object({
    // Null when PostHog couldn't sign a POST, in which case it sends a PUT URL.
    presigned_url: PresignedPost.nullish(),
    fallback_presigned_url: PresignedPost.nullish(),
    presigned_put_url: z.string().nullish(),
    fallback_presigned_put_url: z.string().nullish(),
    symbol_set_id: z.string(),
})

type StartEntry = z.output<typeof StartEntry>

const CheckResponse = z.object({ chunk_ids_to_upload: z.array(z.string()) })
const StartResponse = z.object({ id_map: z.record(z.string(), StartEntry).nullish() })

type Target = { kind: 'put'; url: string } | { kind: 'post'; form: PresignedPost }

export class SymbolSetClient {
    private readonly throttle: Throttle
    // Set once a fallback endpoint worked after the primary failed, so later uploads skip the primary.
    private preferFallback = false

    constructor(
        private readonly runtime: Runtime,
        private readonly session: KeySession,
        private readonly onFallback: () => void = () => {}
    ) {
        this.throttle = new Throttle(runtime, RATE_LIMIT_PER_MINUTE)
    }

    // Project-scoped API URL. hostUrl keeps the path a self-hosted PostHog sits under, which
    // posthog-cli's `Url::join` drops, and gives the same URL for a host without one.
    projectUrl(path: string): URL {
        const { projectId, host } = this.session.current
        return new URL(path, hostUrl(host, `api/projects/${projectId}/`))
    }

    async api<T>(method: 'GET' | 'POST', path: string, schema: Schema<T>, body?: unknown): Promise<T> {
        await this.throttle.wait()
        const url = this.projectUrl(path)
        const response = await this.session.send(
            (token) => sendRequest(this.runtime.fetch, url, { method, body, token, timeoutMs: REQUEST_TIMEOUT_MS }),
            (answer) => answer.status === 401
        )
        if (!response.ok) {
            throw new ApiFailure(response.status, response.text, url.toString())
        }
        const failure = {
            code: 'unexpected_response',
            context: `PostHog's answer to ${method} ${url.pathname} isn't what hog expects.`,
        }
        if (response.text && response.json === undefined) {
            throw failWith(failure, "The answer isn't JSON.")
        }
        return parseOrThrow(schema, response.json, failure)
    }

    async upload(uploads: SymbolSetUpload[], options: UploadOptions): Promise<UploadOutcome> {
        const runId = uuidv7(this.runtime.now())
        try {
            return await this.uploadOnce(uploads, options, runId)
        } catch (error) {
            if (!(error instanceof ReleaseIdMismatch)) {
                throw error
            }
            // posthog-cli always retries the whole run without release ids when the server says a
            // chunk already belongs to another release (`--skip-release-on-fail` can't be turned off).
            return await this.uploadOnce(
                uploads.map((upload) => ({ ...upload, releaseId: null })),
                options,
                runId
            )
        }
    }

    private async uploadOnce(
        uploads: SymbolSetUpload[],
        options: UploadOptions,
        runId: string
    ): Promise<UploadOutcome> {
        const status = options.progress ?? new Map<string, UploadStatus>()
        const contentHashes = new Map<string, string>()
        const kept: (SymbolSetUpload & { hash: string })[] = []
        for (const upload of uploads) {
            if (upload.data.length > MAX_FILE_SIZE) {
                status.set(upload.chunkId, 'too_large')
                continue
            }
            const hash = upload.contentHash ?? contentHash(upload.data)
            contentHashes.set(upload.chunkId, hash)
            kept.push({ ...upload, hash })
        }

        const needed = await this.check(kept, options)
        for (const upload of kept) {
            if (!needed.has(upload.chunkId)) {
                status.set(upload.chunkId, 'already_present')
            }
        }
        const toSend = kept.filter((upload) => needed.has(upload.chunkId))
        for (let start = 0; start < toSend.length; start += options.batchSize) {
            const batch = toSend.slice(start, start + options.batchSize)
            for (const [chunkId, result] of await this.uploadBatch(batch, options, runId)) {
                status.set(chunkId, result)
            }
        }
        return { status, contentHashes }
    }

    private entry(upload: SymbolSetUpload & { hash: string }): {
        chunk_id: string
        release_id: string | null
        content_hash: string
        content_length: number
    } {
        return {
            chunk_id: upload.chunkId,
            release_id: upload.releaseId,
            content_hash: upload.hash,
            content_length: upload.data.length,
        }
    }

    // Asks which chunks the server still needs. A failed check is not fatal: every chunk from the
    // failed slice onward is sent, and the start call decides.
    private async check(uploads: (SymbolSetUpload & { hash: string })[], options: UploadOptions): Promise<Set<string>> {
        const needed = new Set<string>()
        for (let start = 0; start < uploads.length; start += CHECK_BATCH_SIZE) {
            const slice = uploads.slice(start, start + CHECK_BATCH_SIZE)
            try {
                // The answer is checked after the retries, because an answer of the wrong shape is
                // not worth sending the request again for.
                const answer = await withRetries(
                    this.runtime,
                    3,
                    () =>
                        this.api('POST', 'error_tracking/symbol_sets/bulk_check_upload', z.unknown(), {
                            symbol_sets: slice.map((upload) => this.entry(upload)),
                            force: options.force,
                            skip_on_conflict: options.skipOnConflict,
                        }),
                    (error) => !(error instanceof ApiFailure && error.status >= 400 && error.status < 500)
                )
                const response = parseOrThrow(CheckResponse, answer, {
                    code: 'unexpected_response',
                    context: "PostHog's answer to the upload check isn't what hog expects.",
                })
                for (const chunkId of response.chunk_ids_to_upload) {
                    needed.add(chunkId)
                }
            } catch {
                for (const upload of uploads.slice(start)) {
                    needed.add(upload.chunkId)
                }
                return needed
            }
        }
        return needed
    }

    private async uploadBatch(
        batch: (SymbolSetUpload & { hash: string })[],
        options: UploadOptions,
        runId: string
    ): Promise<Map<string, UploadStatus>> {
        const attemptId = uuidv7(this.runtime.now())
        let idMap: Record<string, StartEntry>
        try {
            const answer = await withRetries(this.runtime, 3, () =>
                this.api('POST', 'error_tracking/symbol_sets/bulk_start_upload', z.unknown(), {
                    symbol_sets: batch.map((upload) => this.entry(upload)),
                    upload_attempt_id: attemptId,
                    upload_run_id: runId,
                    force: options.force,
                    skip_on_conflict: options.skipOnConflict,
                })
            )
            idMap =
                parseOrThrow(StartResponse, answer, {
                    code: 'unexpected_response',
                    context: "PostHog's answer to the upload start isn't what hog expects.",
                }).id_map ?? {}
        } catch (error) {
            throw startFailure(error)
        }

        const results = new Map<string, UploadStatus>()
        const byChunk = new Map(batch.map((upload) => [upload.chunkId, upload]))
        for (const upload of batch) {
            if (!(upload.chunkId in idMap)) {
                results.set(upload.chunkId, 'already_present')
            }
        }
        const entries = Object.entries(idMap)
        if (entries.length === 0) {
            return results
        }
        for (const [chunkId] of entries) {
            if (!byChunk.has(chunkId)) {
                throw new HogError(
                    'unexpected_response',
                    `PostHog returned an upload URL for chunk ${chunkId}, which hog didn't send.`
                )
            }
        }
        await runWithConcurrency(entries, options.concurrency ?? 10, async ([chunkId, entry]) => {
            await this.store(byChunk.get(chunkId)!.data, entry)
        })
        const finishHashes: Record<string, string> = {}
        for (const [chunkId, entry] of entries) {
            finishHashes[entry.symbol_set_id] = byChunk.get(chunkId)!.hash
            results.set(chunkId, 'uploaded')
        }
        try {
            await withRetries(this.runtime, 3, () =>
                this.api('POST', 'error_tracking/symbol_sets/bulk_finish_upload', z.unknown(), {
                    content_hashes: finishHashes,
                    upload_attempt_id: attemptId,
                    upload_run_id: runId,
                })
            )
        } catch (error) {
            throw new HogError(
                'upload_not_finished',
                `PostHog didn't confirm the upload, so the symbol sets aren't attached: ${describe(error)}`,
                'Run the upload again. Chunks that already reached PostHog are skipped.'
            )
        }
        return results
    }

    // Sends one container to object storage. A target falls back to its alternate endpoint after two
    // transport errors in a row on the primary, like posthog-cli's endpoint router.
    private async store(data: Uint8Array, entry: StartEntry): Promise<void> {
        const primary: Target | undefined = entry.presigned_put_url
            ? { kind: 'put', url: entry.presigned_put_url }
            : entry.presigned_url
              ? { kind: 'post', form: entry.presigned_url }
              : undefined
        if (primary === undefined) {
            throw new HogError(
                'unexpected_response',
                `PostHog sent no upload URL for symbol set ${entry.symbol_set_id}.`,
                'Run the upload again.'
            )
        }
        const fallbackUrl = entry.presigned_put_url ? entry.fallback_presigned_put_url : entry.fallback_presigned_url
        const fallback: Target | undefined = !fallbackUrl
            ? undefined
            : typeof fallbackUrl === 'string'
              ? { kind: 'put', url: fallbackUrl }
              : { kind: 'post', form: fallbackUrl }
        let primaryTransportErrors = 0
        let fallbackTransportErrors = 0
        await withRetries(this.runtime, fallback ? 4 : 3, async () => {
            const useFallback = fallback !== undefined && (this.preferFallback || primaryTransportErrors >= 2)
            const target = useFallback ? fallback! : primary
            let response: Response
            try {
                response = await this.send(data, target)
            } catch (error) {
                if (useFallback) {
                    fallbackTransportErrors++
                } else {
                    primaryTransportErrors++
                }
                throw error
            }
            if (!useFallback) {
                primaryTransportErrors = 0
            }
            if (!response.ok) {
                throw new HogError('upload_failed', await storageFailure(response, target))
            }
            if (useFallback && primaryTransportErrors >= 2 && fallbackTransportErrors === 0 && !this.preferFallback) {
                this.preferFallback = true
                this.onFallback()
            }
        }).catch((error) => {
            throw new HogError(
                'upload_failed',
                `hog couldn't upload a symbol set: ${describe(error)}`,
                'Check your network connection and run the upload again.'
            )
        })
    }

    private send(data: Uint8Array, target: Target): Promise<Response> {
        if (target.kind === 'put') {
            return this.runtime.fetch(target.url, {
                method: 'PUT',
                body: data as BodyInit,
                timeoutMs: transferTimeout(data.length),
                skipRateLimit: true,
            })
        }
        const form = new FormData()
        for (const [key, value] of Object.entries(target.form.fields)) {
            form.append(key, value)
        }
        // SeaweedFS and MinIO need a filename on the file part.
        form.append('file', new Blob([data as BlobPart]), 'file')
        return this.runtime.fetch(target.form.url, {
            method: 'POST',
            body: form,
            timeoutMs: transferTimeout(data.length),
            skipRateLimit: true,
        })
    }
}

// A presigned URL carries temporary storage credentials in its query, and S3 can echo them back in
// an error's Message or CanonicalRequest. The failure keeps only the path, the Code and the RequestId.
async function storageFailure(response: Response, target: Target): Promise<string> {
    const url = target.kind === 'put' ? target.url : target.form.url
    const summary = storageErrorSummary(await response.text())
    return `Object storage answered ${response.status} for ${withoutQuery(url)}${summary ? ` (${summary})` : ''}.`
}

function withoutQuery(url: string): string {
    return url.split(/[?#]/, 1)[0]!
}

function storageErrorSummary(body: string): string | undefined {
    const fields = ['Code', 'RequestId'].flatMap((name) => {
        const value = body.match(new RegExp(`<${name}>([^<]*)</${name}>`))?.[1]
        return value === undefined ? [] : [`${name}=${value}`]
    })
    return fields.length > 0 ? fields.join(' ') : undefined
}

function describe(error: unknown): string {
    return error instanceof Error ? error.message : String(error)
}

function startFailure(error: unknown): Error {
    if (error instanceof ApiFailure && error.hasCode('release_id_mismatch')) {
        return new ReleaseIdMismatch()
    }
    if (error instanceof ApiFailure && error.hasCode('content_hash_mismatch')) {
        return new HogError(
            'content_hash_mismatch',
            'PostHog already has a symbol set with this chunk ID and different content.',
            'Pass --force to replace it, or --skip-on-conflict to keep the existing one.'
        )
    }
    return new HogError('upload_failed', `PostHog didn't start the upload: ${describe(error)}`)
}

// Like posthog-cli's thread pool: after the first failure no new item starts, and the call returns
// that failure once the items in flight are done.
async function runWithConcurrency<T>(items: T[], limit: number, work: (item: T) => Promise<void>): Promise<void> {
    let next = 0
    let failure: { error: unknown } | undefined
    const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
        while (failure === undefined && next < items.length) {
            try {
                await work(items[next++]!)
            } catch (error) {
                failure ??= { error }
            }
        }
    })
    await Promise.all(workers)
    if (failure !== undefined) {
        throw failure.error
    }
}

export { ApiFailure }
