import { IncomingMessage, Server, ServerResponse, createServer } from 'http'
import { AddressInfo } from 'net'

import { parseJSON } from '~/common/utils/json-parse'

export const TOKEN = 'phc_fake_scenario_runs_token'
export const READ_KEY = 'phx_fake_scenario_runs_read_key'
export const PROJECT_ID = '4242'
const CAPTURE_KEYS = ['api_key', 'event', 'distinct_id', 'uuid', 'timestamp', 'properties']
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

export type Captured = { [key: string]: unknown; properties: Record<string, unknown> }

export type FakeProjectApi = {
    url: string
    credentials: NodeJS.ProcessEnv
    captured: Captured[]
    queries: number
    hideForQueries: number
    close(): Promise<void>
}

function answer(response: ServerResponse, status: number, body: unknown): void {
    response.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(body))
}

async function bodyOf(request: IncomingMessage): Promise<any> {
    const chunks: Buffer[] = []
    for await (const chunk of request) {
        chunks.push(chunk as Buffer)
    }
    try {
        return parseJSON(Buffer.concat(chunks).toString('utf8'))
    } catch {
        return undefined
    }
}

export async function startFakeProjectApi(): Promise<FakeProjectApi> {
    const fake = { captured: [] as Captured[], queries: 0, hideForQueries: 0 }
    const server: Server = createServer((request, response) => {
        void (async () => {
            const body = await bodyOf(request)
            const json = request.headers['content-type'] === 'application/json'
            if (request.method === 'POST' && (request.url === '/i/v0/e/' || request.url === '/i/v0/e')) {
                const unknown = Object.keys(body ?? {}).filter((key) => !CAPTURE_KEYS.includes(key))
                if (!json || body?.api_key !== TOKEN) {
                    return answer(response, 401, { type: 'authentication_error' })
                }
                if (unknown.length > 0 || typeof body.event !== 'string' || typeof body.distinct_id !== 'string') {
                    return answer(response, 400, { type: 'validation_error', unknown })
                }
                if (typeof body.uuid !== 'string' || !UUID.test(body.uuid)) {
                    return answer(response, 400, { type: 'validation_error', attr: 'uuid' })
                }
                fake.captured.push(body)
                return answer(response, 200, { status: 'Ok' })
            }
            if (request.method === 'POST' && request.url === `/api/projects/${PROJECT_ID}/query/`) {
                if (request.headers.authorization !== `Bearer ${READ_KEY}`) {
                    return answer(response, 401, { type: 'authentication_error' })
                }
                const query = body?.query
                const placeholders = [...String(query?.query).matchAll(/\{(\w+)\}/g)].map(([, name]) => name)
                if (
                    !json ||
                    Object.keys(body).join() !== 'query' ||
                    query.kind !== 'HogQLQuery' ||
                    typeof query.query !== 'string' ||
                    Object.keys(query).some((key) => !['kind', 'query', 'values'].includes(key)) ||
                    placeholders.some((name) => query.values?.[name] === undefined)
                ) {
                    return answer(response, 400, { type: 'validation_error' })
                }
                fake.queries += 1
                const visible = fake.queries > fake.hideForQueries
                const rows = fake.captured
                    .filter((event) => visible && event.properties.run_id === query.values?.run_id)
                    .map(({ uuid }) => [uuid])
                return answer(response, 200, { columns: ['uuid'], results: rows })
            }
            return answer(response, 404, { type: 'invalid_request' })
        })()
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo
    const url = `http://127.0.0.1:${port}`
    return Object.assign(fake, {
        url,
        credentials: {
            SCENARIO_RUNS_HOST: `${url}/`,
            SCENARIO_RUNS_PROJECT_ID: PROJECT_ID,
            SCENARIO_RUNS_PROJECT_TOKEN: TOKEN,
            SCENARIO_RUNS_READ_KEY: READ_KEY,
        },
        close: () => new Promise<void>((resolve) => server.close(() => resolve())),
    })
}
