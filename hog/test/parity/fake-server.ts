import { createHash } from 'node:crypto'

// A fake PostHog API plus object store that records every request. Parity tests run posthog-cli and
// hog against it and compare the recordings. Server-side ids are derived from the request (UUIDv5),
// so both CLIs see the same ids.

export type Scenario = 'fresh' | 'post-only' | 'hash-mismatch' | 'release-mismatch' | 'check-403' | 'start-500-once'

export interface RecordedRequest {
    method: string
    path: string
    headers: Record<string, string>
    // API bodies as text. Object-storage bodies are summarized, because they are containers.
    body?: string
    upload?: { sha512: string; length: number; fields?: Record<string, string>; filename?: string }
    status: number
}

export interface FakeServer {
    url: string
    requests: RecordedRequest[]
    seed(entries: { chunkId: string; contentHash: string; releaseId?: string | null }[]): void
    // Stored symbol sets that the download endpoints serve.
    store(objects: StoredObject[]): void
    stop(): void
}

const NAMESPACE = Buffer.from('6ba7b8119dad11d180b400c04fd430c8', 'hex')

function uuid5(name: string): string {
    const hash = createHash('sha1').update(NAMESPACE).update(name).digest()
    hash[6] = (hash[6]! & 0x0f) | 0x50
    hash[8] = (hash[8]! & 0x3f) | 0x80
    const hex = hash.subarray(0, 16).toString('hex')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export interface StoredObject {
    id: string
    ref: string
    data: Uint8Array
}

interface StoredSymbolSet {
    id: string
    hash: string | null
    releaseId: string | null
}

const RECORDED_HEADERS = ['authorization', 'content-type', 'user-agent']

export function startFakeServer(scenario: Scenario): FakeServer {
    const requests: RecordedRequest[] = []
    const symbolSets = new Map<string, StoredSymbolSet>()
    const releases = new Map<string, unknown>()
    const objects: StoredObject[] = []
    let startCalls = 0

    const json = (status: number, body: unknown): Response =>
        new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
    const apiError = (status: number, code: string, detail: string): Response =>
        json(status, { type: 'validation_error', code, detail, attr: null })

    const server = Bun.serve({
        port: 0,
        hostname: '127.0.0.1',
        async fetch(request): Promise<Response> {
            const url = new URL(request.url)
            const headers: Record<string, string> = {}
            for (const name of RECORDED_HEADERS) {
                const value = request.headers.get(name)
                if (value !== null) {
                    headers[name] = name === 'authorization' ? value.replace(/phx_\w+/, 'phx_<key>') : value
                }
            }
            const entry: RecordedRequest = {
                method: request.method,
                path: url.pathname + url.search,
                headers,
                status: 0,
            }
            requests.push(entry)
            const respond = (response: Response): Response => {
                entry.status = response.status
                return response
            }

            if (url.pathname.startsWith('/s3/get/')) {
                const object = objects.find((candidate) => url.pathname === `/s3/get/${candidate.id}`)
                return respond(
                    object
                        ? new Response(Buffer.from(object.data))
                        : new Response('<Error>NoSuchKey</Error>', { status: 404 })
                )
            }
            if (url.pathname.startsWith('/s3/')) {
                return respond(await storeObject(request, url, entry))
            }
            const body = await request.text()
            if (body) {
                entry.body = body
            }
            const path = url.pathname.replace(/\/$/, '')
            const base = `http://127.0.0.1:${server.port}`
            let match: RegExpMatchArray | null

            if ((match = path.match(/^\/api\/projects\/\d+\/error_tracking\/releases\/hash\/(.+)$/))) {
                const release = releases.get(match[1]!)
                return respond(
                    release
                        ? json(200, release)
                        : json(404, { type: 'invalid_request', code: 'not_found', detail: 'Not found.', attr: null })
                )
            }
            if (/^\/api\/projects\/\d+\/error_tracking\/releases$/.test(path) && request.method === 'POST') {
                const parsed = JSON.parse(body) as {
                    hash_id: string
                    version: string
                    project: string
                    metadata?: unknown
                }
                const release = {
                    id: uuid5(`release:${parsed.hash_id}`),
                    hash_id: parsed.hash_id,
                    version: parsed.version,
                    project: parsed.project,
                }
                releases.set(parsed.hash_id, release)
                return respond(json(201, release))
            }
            if (/^\/api\/projects\/\d+\/error_tracking\/symbol_sets$/.test(path) && request.method === 'GET') {
                const found = objects.filter((object) => object.ref === url.searchParams.get('ref'))
                return respond(
                    json(200, { results: found.slice(0, 1).map((object) => ({ id: object.id, ref: object.ref })) })
                )
            }
            if ((match = path.match(/^\/api\/projects\/\d+\/error_tracking\/symbol_sets\/([^/]+)\/download$/))) {
                const id = match[1]
                const object = objects.find((candidate) => candidate.id === id)
                return respond(
                    object ? json(200, { url: `${base}/s3/get/${object.id}` }) : json(404, { detail: 'Not found.' })
                )
            }
            if (path.endsWith('/symbol_sets/bulk_check_upload')) {
                if (scenario === 'check-403') {
                    return respond(
                        json(403, {
                            type: 'authentication_error',
                            code: 'permission_denied',
                            detail: 'No.',
                            attr: null,
                        })
                    )
                }
                const parsed = JSON.parse(body) as { symbol_sets: { chunk_id: string; content_hash: string }[] }
                const needed = parsed.symbol_sets
                    .filter((set) => symbolSets.get(set.chunk_id)?.hash !== set.content_hash)
                    .map((set) => set.chunk_id)
                return respond(json(200, { chunk_ids_to_upload: needed }))
            }
            if (path.endsWith('/symbol_sets/bulk_start_upload')) {
                startCalls++
                if (scenario === 'start-500-once' && startCalls === 1) {
                    return respond(json(500, { detail: 'Server error.' }))
                }
                const parsed = JSON.parse(body) as {
                    symbol_sets: {
                        chunk_id: string
                        release_id: string | null
                        content_hash: string
                        content_length?: number
                    }[]
                    force: boolean
                    skip_on_conflict: boolean
                }
                // The stored copy has other content: an error unless the request says what to do.
                if (scenario === 'hash-mismatch' && !parsed.force) {
                    if (!parsed.skip_on_conflict) {
                        return respond(
                            apiError(
                                400,
                                'content_hash_mismatch',
                                'A symbol set with this chunk ID already has different content.'
                            )
                        )
                    }
                    return respond(json(201, { id_map: {} }))
                }
                if (scenario === 'release-mismatch' && parsed.symbol_sets.some((set) => set.release_id !== null)) {
                    return respond(
                        apiError(400, 'release_id_mismatch', 'The symbol set already belongs to another release.')
                    )
                }
                const idMap: Record<string, unknown> = {}
                for (const set of parsed.symbol_sets) {
                    if (symbolSets.get(set.chunk_id)?.hash === set.content_hash) {
                        continue
                    }
                    const id = uuid5(`symbol_set:${set.chunk_id}`)
                    symbolSets.set(set.chunk_id, { id, hash: null, releaseId: set.release_id })
                    const key = `symbolsets/${id}`
                    const item: Record<string, unknown> = {
                        presigned_url: {
                            url: `${base}/s3/post`,
                            fields: { key, policy: 'policy', 'x-amz-signature': 'signature' },
                        },
                        symbol_set_id: id,
                    }
                    if (scenario !== 'post-only' && set.content_length !== undefined) {
                        item.presigned_put_url = `${base}/s3/put/${key}?length=${set.content_length}`
                    }
                    idMap[set.chunk_id] = item
                }
                return respond(json(201, { id_map: idMap }))
            }
            if (path.endsWith('/symbol_sets/bulk_finish_upload')) {
                const parsed = JSON.parse(body) as { content_hashes: Record<string, string> }
                for (const [id, hash] of Object.entries(parsed.content_hashes)) {
                    for (const set of symbolSets.values()) {
                        if (set.id === id) {
                            set.hash = hash
                        }
                    }
                }
                return respond(json(201, { success: true }))
            }
            return respond(json(404, { detail: `No fake for ${request.method} ${url.pathname}` }))
        },
    })

    return {
        url: `http://127.0.0.1:${server.port}`,
        requests,
        seed(entries) {
            for (const entry of entries) {
                symbolSets.set(entry.chunkId, {
                    id: uuid5(`symbol_set:${entry.chunkId}`),
                    hash: entry.contentHash,
                    releaseId: entry.releaseId ?? null,
                })
            }
        },
        store(stored) {
            objects.push(...stored)
        },
        stop: () => server.stop(true),
    }
}

async function storeObject(request: Request, url: URL, entry: RecordedRequest): Promise<Response> {
    if (request.method === 'PUT') {
        const body = new Uint8Array(await request.arrayBuffer())
        entry.upload = { sha512: createHash('sha512').update(body).digest('hex'), length: body.length }
        // A presigned PUT signs the content length, so a different length fails like it does on S3.
        if (Number(url.searchParams.get('length')) !== body.length) {
            return new Response('<Error>SignatureDoesNotMatch</Error>', { status: 403 })
        }
        return new Response(null, { status: 200 })
    }
    const form = await request.formData()
    const fields: Record<string, string> = {}
    let file: File | undefined
    for (const [name, value] of form.entries()) {
        if (typeof value === 'string') {
            fields[name] = value
        } else {
            file = value
        }
    }
    const body = file ? new Uint8Array(await file.arrayBuffer()) : new Uint8Array()
    entry.upload = {
        sha512: createHash('sha512').update(body).digest('hex'),
        length: body.length,
        fields,
        filename: file?.name,
    }
    return new Response(null, { status: 204 })
}
