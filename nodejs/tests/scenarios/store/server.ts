import { createHash, timingSafeEqual } from 'crypto'
import { IncomingMessage, Server, ServerResponse, createServer } from 'http'
import { AddressInfo } from 'net'
import { Pool } from 'pg'
import { promisify } from 'util'
import { gunzip } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'

import { RunReport, RunStore } from './runs'
import { migrate } from './schema'

// Only this path is opened past the host's sign-in, so it is the one path that checks the run token.
export const INGEST_PATH = '/api/ingest/runs'
export const RUNS_PATH = '/api/runs'

const MAX_BODY_BYTES = 32 * 1024 * 1024
const DEFAULT_LIMIT = 100
const MAX_LIMIT = 500
const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
// The managed database caps an app at 20 connections and every statement at 30 seconds.
const POOL_SIZE = 5
const STATEMENT_TIMEOUT_MS = 25_000

const gunzipAsync = promisify(gunzip)

class HttpError extends Error {
    constructor(
        readonly status: number,
        message: string
    ) {
        super(message)
    }
}

const digest = (value: string): Buffer => createHash('sha256').update(value).digest()

function tokenMatches(header: string | undefined, expected: Buffer): boolean {
    const match = /^Bearer (.+)$/.exec(header ?? '')
    return match !== null && timingSafeEqual(digest(match[1]), expected)
}

async function bodyOf(request: IncomingMessage): Promise<unknown> {
    const chunks: Buffer[] = []
    let size = 0
    for await (const chunk of request) {
        size += (chunk as Buffer).length
        if (size > MAX_BODY_BYTES) {
            throw new HttpError(413, `the body is larger than ${MAX_BODY_BYTES} bytes`)
        }
        chunks.push(chunk as Buffer)
    }
    let raw = Buffer.concat(chunks)
    if (request.headers['content-encoding'] === 'gzip') {
        raw = await gunzipAsync(raw, { maxOutputLength: MAX_BODY_BYTES }).catch(() => {
            throw new HttpError(400, 'the gzipped body does not decompress within the size limit')
        })
    }
    try {
        return parseJSON(raw.toString('utf8'))
    } catch {
        throw new HttpError(400, 'the body is not JSON')
    }
}

function send(response: ServerResponse, status: number, body: unknown): void {
    response.writeHead(status, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify(body))
}

function limitOf(value: string | null): number {
    if (value === null) {
        return DEFAULT_LIMIT
    }
    const limit = Number(value)
    if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
        throw new HttpError(400, `limit must be a whole number from 1 to ${MAX_LIMIT}`)
    }
    return limit
}

async function handle(
    store: RunStore,
    token: Buffer,
    request: IncomingMessage,
    response: ServerResponse
): Promise<void> {
    const url = new URL(request.url ?? '/', 'http://store')
    if (url.pathname === INGEST_PATH) {
        if (request.method !== 'POST') {
            throw new HttpError(405, 'use POST')
        }
        if (!tokenMatches(request.headers.authorization, token)) {
            throw new HttpError(401, 'a valid run token is required')
        }
        const parsed = RunReport.safeParse(await bodyOf(request))
        if (!parsed.success) {
            throw new HttpError(
                400,
                parsed.error.issues.map(({ path, message }) => `${path.join('.')}: ${message}`).join('; ')
            )
        }
        const stored = await store.put(parsed.data)
        return send(response, stored === 'created' ? 201 : 200, { runId: parsed.data.scorecard.run_id, stored })
    }
    if (request.method !== 'GET') {
        throw new HttpError(405, 'use GET')
    }
    if (url.pathname === RUNS_PATH) {
        const runs = await store.list({
            cardId: url.searchParams.get('card_id') ?? undefined,
            limit: limitOf(url.searchParams.get('limit')),
        })
        return send(response, 200, { runs })
    }
    if (url.pathname.startsWith(`${RUNS_PATH}/`)) {
        const runId = url.pathname.slice(RUNS_PATH.length + 1)
        if (!RUN_ID.test(runId)) {
            throw new HttpError(400, 'the run id is not a lowercase UUID')
        }
        const run = await store.get(runId)
        if (run === undefined) {
            throw new HttpError(404, 'no run with that id')
        }
        return send(response, 200, run)
    }
    throw new HttpError(404, 'not found')
}

export type StoreOptions = { databaseUrl: string; token: string; port: number; host?: string }

export type RunningStore = { url: string; close: () => Promise<void> }

// Migrations finish before the port opens, so a new revision never serves an old schema.
export async function startStore({ databaseUrl, token, port, host = '0.0.0.0' }: StoreOptions): Promise<RunningStore> {
    if (token === '') {
        throw new Error('the store needs a run token to check reports against')
    }
    const pool = new Pool({
        connectionString: databaseUrl,
        max: POOL_SIZE,
        statement_timeout: STATEMENT_TIMEOUT_MS,
    })
    // An idle client the server drops would otherwise throw from an event handler and end the process.
    pool.on('error', () => undefined)
    try {
        await migrate(pool)
    } catch (error) {
        await pool.end()
        throw error
    }
    const store = new RunStore(pool)
    const expected = digest(token)
    const server: Server = createServer((request, response) => {
        handle(store, expected, request, response).catch((error: unknown) => {
            if (error instanceof HttpError) {
                return send(response, error.status, { error: error.message })
            }
            process.stderr.write(`store: ${request.method} ${request.url?.split('?')[0]}: ${String(error)}\n`)
            send(response, 500, { error: 'the store failed to answer' })
        })
    })
    await new Promise<void>((resolve, reject) => {
        server.once('error', reject)
        server.listen(port, host, resolve)
    })
    const { port: bound } = server.address() as AddressInfo
    return {
        url: `http://${host === '0.0.0.0' ? '127.0.0.1' : host}:${bound}`,
        close: async () => {
            const closed = new Promise<void>((resolve) => server.close(() => resolve()))
            server.closeAllConnections()
            await closed
            await pool.end()
        },
    }
}
