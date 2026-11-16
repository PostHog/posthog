import { createHash, timingSafeEqual } from 'crypto'
import { IncomingMessage, Server, ServerResponse, createServer } from 'http'
import { AddressInfo } from 'net'
import { Pool } from 'pg'
import { promisify } from 'util'
import { gunzip } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'

import { RunId, RunReport, RunStore } from './runs'
import { migrate } from './schema'

export const INGEST_PATH = '/api/ingest/runs'
export const RUNS_PATH = '/api/runs'

const MAX_BODY_BYTES = 32 * 1024 * 1024
const DEFAULT_LIMIT = 100
const MAX_LIMIT = 500
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

const tooLarge = (): HttpError => new HttpError(413, `the body is larger than ${MAX_BODY_BYTES} bytes`)

const digest = (value: string): Buffer => createHash('sha256').update(value).digest()

function tokenMatches(header: string | undefined, expected: Buffer): boolean {
    const match = /^Bearer (.+)$/.exec(header ?? '')
    return match !== null && timingSafeEqual(digest(match[1]), expected)
}

function rawBodyOf(request: IncomingMessage): Promise<Buffer> {
    if (Number(request.headers['content-length'] ?? 0) > MAX_BODY_BYTES) {
        return Promise.reject(tooLarge())
    }
    return new Promise((resolve, reject) => {
        const chunks: Buffer[] = []
        let size = 0
        const onData = (chunk: Buffer): void => {
            size += chunk.length
            if (size > MAX_BODY_BYTES) {
                request.off('data', onData)
                reject(tooLarge())
                return
            }
            chunks.push(chunk)
        }
        request.on('data', onData)
        request.once('end', () => resolve(Buffer.concat(chunks)))
        request.once('error', reject)
    })
}

async function decodedBodyOf(request: IncomingMessage): Promise<Buffer> {
    const raw = await rawBodyOf(request)
    if (request.headers['content-encoding'] !== 'gzip') {
        return raw
    }
    return await gunzipAsync(raw, { maxOutputLength: MAX_BODY_BYTES }).catch((error: NodeJS.ErrnoException) => {
        throw error.code === 'ERR_BUFFER_TOO_LARGE' ? tooLarge() : new HttpError(400, 'the body is not valid gzip')
    })
}

async function reportOf(request: IncomingMessage): Promise<RunReport> {
    const body = (await decodedBodyOf(request)).toString('utf8')
    let json: unknown
    try {
        json = parseJSON(body)
    } catch {
        throw new HttpError(400, 'the body is not JSON')
    }
    const parsed = RunReport.safeParse(json)
    if (!parsed.success) {
        throw new HttpError(
            400,
            parsed.error.issues.map(({ path, message }) => `${path.join('.')}: ${message}`).join('; ')
        )
    }
    return parsed.data
}

function send(response: ServerResponse, status: number, body: unknown): void {
    response.writeHead(status, {
        'Content-Type': 'application/json',
        ...(status === 413 ? { Connection: 'close' } : {}),
    })
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

function requireMethod(request: IncomingMessage, method: 'GET' | 'POST'): void {
    if (request.method !== method) {
        throw new HttpError(405, `use ${method}`)
    }
}

async function ingest(store: RunStore, token: Buffer, request: IncomingMessage, response: ServerResponse) {
    requireMethod(request, 'POST')
    if (!tokenMatches(request.headers.authorization, token)) {
        throw new HttpError(401, 'a valid run token is required')
    }
    const report = await reportOf(request)
    const stored = await store.put(report)
    send(response, stored === 'created' ? 201 : 200, { runId: report.scorecard.run_id, stored })
}

async function listRuns(store: RunStore, query: URLSearchParams, request: IncomingMessage, response: ServerResponse) {
    requireMethod(request, 'GET')
    const runs = await store.list({ cardId: query.get('card_id') || undefined, limit: limitOf(query.get('limit')) })
    send(response, 200, { runs })
}

async function readRun(store: RunStore, id: string, request: IncomingMessage, response: ServerResponse) {
    requireMethod(request, 'GET')
    const runId = RunId.safeParse(id)
    if (!runId.success) {
        throw new HttpError(400, 'the run id is not a UUID')
    }
    const run = await store.get(runId.data)
    if (run === undefined) {
        throw new HttpError(404, 'no run with that id')
    }
    send(response, 200, run)
}

async function handle(store: RunStore, token: Buffer, request: IncomingMessage, response: ServerResponse) {
    const [path, query = ''] = (request.url ?? '/').split('?', 2)
    if (path === INGEST_PATH) {
        return await ingest(store, token, request, response)
    }
    if (path === RUNS_PATH) {
        return await listRuns(store, new URLSearchParams(query), request, response)
    }
    if (path.startsWith(`${RUNS_PATH}/`)) {
        return await readRun(store, path.slice(RUNS_PATH.length + 1), request, response)
    }
    throw new HttpError(404, 'not found')
}

export type StoreOptions = { databaseUrl: string; token: string; port: number; host?: string }

export type RunningStore = { url: string; close: () => Promise<void> }

export async function startStore({
    databaseUrl,
    token,
    port,
    host = '127.0.0.1',
}: StoreOptions): Promise<RunningStore> {
    if (token === '') {
        throw new Error('the store needs a run token to check reports against')
    }
    const pool = new Pool({ connectionString: databaseUrl, max: POOL_SIZE, statement_timeout: STATEMENT_TIMEOUT_MS })
    pool.on('error', () => undefined)
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
    try {
        await migrate(pool)
        await new Promise<void>((resolve, reject) => {
            server.once('error', reject)
            server.listen(port, host, resolve)
        })
    } catch (error) {
        await pool.end()
        throw error
    }
    const { port: bound } = server.address() as AddressInfo
    return {
        url: `http://${host === '0.0.0.0' ? '127.0.0.1' : host}:${bound}`,
        close: async () => {
            await new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())))
            await pool.end()
        },
    }
}
