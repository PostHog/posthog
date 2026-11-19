import { randomUUID } from 'crypto'
import { request as httpRequest } from 'http'
import { AddressInfo, Socket, createServer as createTcpServer } from 'net'
import { gzipSync } from 'zlib'

import { defaultConfig } from '~/common/config/config'
import { internalFetch } from '~/common/utils/request'

import { scratchSchema } from '../environment/stack'
import { SCHEMA_VERSION } from '../scorecard/scorecard'
import { INGEST_PATH, RUNS_PATH } from './routes'
import { RunningStore, startStore } from './server'

const TOKEN = 'test-run-token'
const AUTHORIZED = { Authorization: `Bearer ${TOKEN}` }
const schema = scratchSchema(defaultConfig.DATABASE_URL, `scenario_store_${process.pid}`, [])

function scorecardFixture(runId: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        schema_version: SCHEMA_VERSION,
        run_id: runId,
        card_id: 'example-card',
        card_hash: 'c0ffee',
        head_sha: 'abc1234',
        target: 'local',
        status: 'passed',
        status_reason: 'every invariant held',
        started_at: '2026-01-02T03:04:05.000Z',
        ended_at: '2026-01-02T03:09:05.000Z',
        evidence_dir: '/tmp/example/evidence',
        adapters: ['example'],
        owners: ['example-team'],
        inv_example_passed: true,
        bars: [{ name: 'example-bar', passed: true }],
        ...overrides,
    }
}

const seriesOf = (name: string, values: number[]) => ({
    adapter: 'example',
    name,
    unit: 'per_second',
    points: values.map((value, index) => ({ at: 1_700_000_000_000 + index * 5000, value })),
})

const paddedPastTheLimit = (runId: string): Buffer =>
    Buffer.from(JSON.stringify({ scorecard: scorecardFixture(runId) }) + ' '.repeat(33 * 1024 * 1024))

const withoutStatus = (runId: string): Record<string, unknown> => {
    const { status: _status, ...scorecard } = scorecardFixture(runId)
    return scorecard
}

describe('run store', () => {
    let store: RunningStore

    const ingest = (body: unknown, headers: Record<string, string> = AUTHORIZED) =>
        internalFetch(`${store.url}${INGEST_PATH}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...headers },
            body: Buffer.isBuffer(body) ? body : JSON.stringify(body),
        })

    const read = async (path: string) => {
        const response = await internalFetch(`${store.url}${path}`)
        return { status: response.status, body: await response.json() }
    }

    const runIdsOf = async (path: string): Promise<string[]> =>
        (await read(path)).body.runs.map((run: { runId: string }) => run.runId)

    beforeAll(async () => {
        await schema.create()
    })

    beforeEach(async () => {
        store = await startStore({ databaseUrl: schema.url, token: TOKEN, port: 0 })
    })

    afterEach(async () => {
        await store.close()
    })

    afterAll(async () => {
        await schema.drop()
    })

    it('reads back exactly what was posted', async () => {
        const runId = randomUUID()
        const series = [
            { ...seriesOf('offered', [3, 4]), labels: { process: 'worker-a' } },
            { ...seriesOf('offered', [5]), labels: { process: 'worker-b' } },
            { ...seriesOf('lag', [1]), points: [{ at: 1, value: null }] },
        ]
        const topology = { nodes: ['a', 'b'], edges: [['a', 'b']] }
        const manifest = { adapters: [{ id: 'example', owner: 'example-team' }] }

        expect(
            (await ingest({ scorecard: scorecardFixture(runId), series, topology, manifest, host: 'box-1' })).status
        ).toBe(201)

        expect(await read(`${RUNS_PATH}/${runId}`)).toEqual({
            status: 200,
            body: {
                runId,
                cardId: 'example-card',
                status: 'passed',
                target: 'local',
                host: 'box-1',
                headSha: 'abc1234',
                cardHash: 'c0ffee',
                startedAt: '2026-01-02T03:04:05.000Z',
                endedAt: '2026-01-02T03:09:05.000Z',
                evidenceDir: '/tmp/example/evidence',
                adapters: ['example'],
                owners: ['example-team'],
                receivedAt: expect.any(String),
                updatedAt: expect.any(String),
                scorecard: scorecardFixture(runId),
                series: series.map((named) => ({ labels: {}, ...named })),
                topology,
                manifest,
            },
        })
    })

    it('stores a scorecard of schema version 2 as given', async () => {
        const runId = randomUUID()
        const scorecard = scorecardFixture(runId, { schema_version: 2 })

        expect((await ingest({ scorecard })).status).toBe(201)

        expect((await read(`${RUNS_PATH}/${runId}`)).body).toMatchObject({ scorecard })
    })

    it('stores a run posted twice once, with the second report', async () => {
        const runId = randomUUID()
        const failed = scorecardFixture(runId, { status: 'failed', status_reason: 'an invariant failed' })

        expect((await ingest({ scorecard: scorecardFixture(runId) })).status).toBe(201)
        expect((await ingest({ scorecard: failed })).status).toBe(200)

        const { body } = await read(`${RUNS_PATH}?card_id=example-card`)
        expect(body.runs.filter((run: { runId: string }) => run.runId === runId)).toEqual([
            expect.objectContaining({ status: 'failed' }),
        ])
        expect((await read(`${RUNS_PATH}/${runId}`)).body).toMatchObject({ scorecard: failed })
    })

    it.each([
        ['leaves them out', {}],
        ['sends them as null', { series: null, topology: null, manifest: null, host: null }],
    ])('keeps the series, topology, manifest and host when a re-report %s', async (_, absent) => {
        const runId = randomUUID()
        const series = [seriesOf('offered', [1, 2, 3])]
        const topology = { nodes: ['a'] }
        const manifest = { adapters: [{ id: 'example' }] }
        await ingest({ scorecard: scorecardFixture(runId), series, topology, manifest, host: 'box-1' })

        expect((await ingest({ scorecard: scorecardFixture(runId), ...absent })).status).toBe(200)

        expect((await read(`${RUNS_PATH}/${runId}`)).body).toMatchObject({ series, topology, manifest, host: 'box-1' })
    })

    it('takes a gzipped report', async () => {
        const runId = randomUUID()
        const body = gzipSync(JSON.stringify({ scorecard: scorecardFixture(runId) }))

        expect((await ingest(body, { ...AUTHORIZED, 'Content-Encoding': 'gzip' })).status).toBe(201)
        expect(await read(`${RUNS_PATH}/${runId}`)).toMatchObject({ status: 200 })
    })

    it('reads a run back by the uppercase id it was reported under', async () => {
        const runId = randomUUID()

        await ingest({ scorecard: scorecardFixture(runId.toUpperCase()) })

        expect(await read(`${RUNS_PATH}/${runId.toUpperCase()}`)).toMatchObject({ status: 200, body: { runId } })
    })

    it.each<[string, (runId: string) => { body: unknown; headers: Record<string, string> }, number]>([
        ['no token', (runId) => ({ body: { scorecard: scorecardFixture(runId) }, headers: {} }), 401],
        [
            'a wrong token',
            (runId) => ({
                body: { scorecard: scorecardFixture(runId) },
                headers: { Authorization: 'Bearer not-the-token' },
            }),
            401,
        ],
        [
            'the token without the Bearer scheme',
            (runId) => ({ body: { scorecard: scorecardFixture(runId) }, headers: { Authorization: TOKEN } }),
            401,
        ],
        [
            'a scorecard without a status',
            (runId) => ({ body: { scorecard: withoutStatus(runId) }, headers: AUTHORIZED }),
            400,
        ],
        [
            'a scorecard of another schema version',
            (runId) => ({ body: { scorecard: scorecardFixture(runId, { schema_version: 3 }) }, headers: AUTHORIZED }),
            400,
        ],
        [
            'a series that is not a list of named series',
            (runId) => ({ body: { scorecard: scorecardFixture(runId), series: { flow: [1] } }, headers: AUTHORIZED }),
            400,
        ],
        [
            'a series point whose value is a string',
            (runId) => ({
                body: {
                    scorecard: scorecardFixture(runId),
                    series: [{ ...seriesOf('offered', [1]), points: [{ at: 1, value: '3' }] }],
                },
                headers: AUTHORIZED,
            }),
            400,
        ],
        [
            'series labels that are not strings',
            (runId) => ({
                body: {
                    scorecard: scorecardFixture(runId),
                    series: [{ ...seriesOf('offered', [1]), labels: { process: 1 } }],
                },
                headers: AUTHORIZED,
            }),
            400,
        ],
        [
            'adapters that are not a list of names',
            (runId) => ({ body: { scorecard: scorecardFixture(runId, { adapters: 'example' }) }, headers: AUTHORIZED }),
            400,
        ],
        [
            'owners that are not a list of names',
            (runId) => ({ body: { scorecard: scorecardFixture(runId, { owners: [''] }) }, headers: AUTHORIZED }),
            400,
        ],
        ['a body that is not JSON', () => ({ body: Buffer.from('{"scorecard":'), headers: AUTHORIZED }), 400],
        [
            'a gzip header on a plain body',
            (runId) => ({
                body: { scorecard: scorecardFixture(runId) },
                headers: { ...AUTHORIZED, 'Content-Encoding': 'gzip' },
            }),
            400,
        ],
        [
            'a gzipped body that unpacks past the size limit',
            (runId) => ({
                body: gzipSync(paddedPastTheLimit(runId)),
                headers: { ...AUTHORIZED, 'Content-Encoding': 'gzip' },
            }),
            413,
        ],
        ['a body past the size limit', (runId) => ({ body: paddedPastTheLimit(runId), headers: AUTHORIZED }), 413],
    ])('refuses a report with %s and stores nothing', async (_, reportOf, status) => {
        const runId = randomUUID()
        const { body, headers } = reportOf(runId)

        const response = await ingest(body, headers)

        expect({ status: response.status, body: await response.json() }).toEqual({
            status,
            body: { error: expect.any(String) },
        })
        expect(await read(`${RUNS_PATH}/${runId}`)).toMatchObject({ status: 404 })
    })

    it.each([
        ['GET', INGEST_PATH, 405],
        ['POST', RUNS_PATH, 405],
        ['DELETE', `${RUNS_PATH}/${randomUUID()}`, 405],
        ['POST', `${INGEST_PATH}/`, 404],
        ['GET', '/api/unknown', 404],
        ['GET', `${RUNS_PATH}/${randomUUID()}/series`, 404],
        ['GET', `${RUNS_PATH}/not-a-run-id`, 400],
        ['GET', `${RUNS_PATH}/${randomUUID()}`, 404],
        ['GET', `${RUNS_PATH}?limit=0`, 400],
        ['GET', `${RUNS_PATH}?limit=501`, 400],
        ['GET', `${RUNS_PATH}?limit=ten`, 400],
    ])('answers %s %s with %i', async (method, path, status) => {
        const response = await internalFetch(`${store.url}${path}`, { method, headers: AUTHORIZED })

        expect({ status: response.status, body: await response.json() }).toEqual({
            status,
            body: { error: expect.any(String) },
        })
    })

    it('answers a path that climbs out of the ingest path with 404, not the runs it names', async () => {
        const { hostname, port } = new URL(store.url)
        const status = await new Promise<number>((resolve, reject) => {
            httpRequest({ hostname, port, path: `${INGEST_PATH}/%2e%2e/%2e%2e/runs` }, (response) => {
                response.resume()
                resolve(response.statusCode ?? 0)
            })
                .on('error', reject)
                .end()
        })

        expect(status).toBe(404)
    })

    it('lists runs newest first, filtered by card, up to the limit', async () => {
        const [oldest, older, newer, other] = [randomUUID(), randomUUID(), randomUUID(), randomUUID()]
        for (const [runId, day] of [
            [oldest, '01'],
            [older, '02'],
            [newer, '03'],
        ]) {
            await ingest({
                scorecard: scorecardFixture(runId, {
                    card_id: 'list-card',
                    started_at: `2026-02-${day}T00:00:00.000Z`,
                }),
            })
        }
        await ingest({ scorecard: scorecardFixture(other, { card_id: 'other-card' }) })

        expect(await runIdsOf(`${RUNS_PATH}?card_id=list-card`)).toEqual([newer, older, oldest])
        expect(await runIdsOf(`${RUNS_PATH}?card_id=list-card&limit=2`)).toEqual([newer, older])
        expect((await read(`${RUNS_PATH}?card_id=list-card&limit=1`)).body.runs[0]).not.toHaveProperty('scorecard')
    })

    it('treats an empty card_id as no filter', async () => {
        const [first, second] = [randomUUID(), randomUUID()]
        const adapters = ['empty-card-filter']
        await ingest({ scorecard: scorecardFixture(first, { card_id: 'first-card', adapters }) })
        await ingest({ scorecard: scorecardFixture(second, { card_id: 'second-card', adapters }) })

        expect(new Set(await runIdsOf(`${RUNS_PATH}?card_id=&adapter=empty-card-filter`))).toEqual(
            new Set([first, second])
        )
    })

    it('lists the runs of one adapter, and keeps no adapter or owner for a run that names none', async () => {
        const [single, shared, none] = [randomUUID(), randomUUID(), randomUUID()]
        const card_id = 'adapter-card'
        await ingest({ scorecard: scorecardFixture(single, { card_id }) })
        await ingest({ scorecard: scorecardFixture(shared, { card_id, adapters: ['other', 'example'] }) })
        await ingest({ scorecard: scorecardFixture(none, { card_id, adapters: undefined, owners: undefined }) })

        expect(await runIdsOf(`${RUNS_PATH}?card_id=${card_id}&adapter=other`)).toEqual([shared])
        expect(new Set(await runIdsOf(`${RUNS_PATH}?card_id=${card_id}&adapter=example`))).toEqual(
            new Set([single, shared])
        )
        expect((await read(`${RUNS_PATH}/${none}`)).body).toMatchObject({ adapters: [], owners: [] })
    })

    it('refuses a streamed body past the size limit that names no length, and stores nothing', async () => {
        const runId = randomUUID()
        const { hostname, port } = new URL(store.url)
        const status = await new Promise<number>((resolve, reject) => {
            let answered = false
            const request = httpRequest({
                hostname,
                port,
                method: 'POST',
                path: INGEST_PATH,
                headers: { ...AUTHORIZED, 'Content-Type': 'application/json', 'Transfer-Encoding': 'chunked' },
            })
            request.on('response', (response) => {
                answered = true
                response.resume()
                resolve(response.statusCode ?? 0)
            })
            request.on('error', (error) => (answered ? undefined : reject(error)))
            request.end(paddedPastTheLimit(runId))
        })

        expect(status).toBe(413)
        expect(await read(`${RUNS_PATH}/${runId}`)).toMatchObject({ status: 404 })
    })

    it('finishes a report already in flight when it closes, even when told to close twice', async () => {
        const runId = randomUUID()
        const body = JSON.stringify({ scorecard: scorecardFixture(runId) })
        const { hostname, port } = new URL(store.url)
        let closed: Promise<unknown> = Promise.resolve()
        const answered = new Promise<number>((resolve, reject) => {
            const request = httpRequest({
                hostname,
                port,
                method: 'POST',
                path: INGEST_PATH,
                headers: { ...AUTHORIZED, 'Content-Length': Buffer.byteLength(body), Expect: '100-continue' },
            })
            request.on('continue', () => {
                closed = Promise.all([store.close(), store.close()])
                request.end(body)
            })
            request.on('response', (response) => {
                response.resume()
                resolve(response.statusCode ?? 0)
            })
            request.on('error', reject)
            request.flushHeaders()
        })

        expect(await answered).toBe(201)
        await closed

        store = await startStore({ databaseUrl: schema.url, token: TOKEN, port: 0 })
        expect(await read(`${RUNS_PATH}/${runId}`)).toMatchObject({ status: 200 })
    })

    it('stops starting when the database takes connections and never answers', async () => {
        const held: Socket[] = []
        const silent = createTcpServer((socket) => held.push(socket))
        await new Promise<void>((resolve) => silent.listen(0, '127.0.0.1', resolve))
        const { port } = silent.address() as AddressInfo
        try {
            await expect(
                startStore({ databaseUrl: `postgres://user:secret@127.0.0.1:${port}/runs`, token: TOKEN, port: 0 })
            ).rejects.toThrow(/timeout/i)
        } finally {
            held.forEach((socket) => socket.destroy())
            await new Promise((resolve) => silent.close(resolve))
        }
    }, 15_000)
})
