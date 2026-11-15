import { ProviderEdge, TruthPage, WEBHOOK_HOST, startProviderEdge } from '.'
import { mkdtempSync, readFileSync, rmSync } from 'fs'
import http from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'
// eslint-disable-next-line no-restricted-imports
import { ProxyAgent, request } from 'undici'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'

import { ValveEntry } from '../cards/schema'
import { ValveContext, createValves } from '../valves/valves'

describe('provider edge proxy', () => {
    let caDir: string
    let edge: ProviderEdge
    let client: ProxyAgent

    beforeEach(async () => {
        caDir = mkdtempSync(path.join(os.tmpdir(), 'provider-edge-ca-'))
        edge = await startProviderEdge({ port: 0, caDir })
        client = new ProxyAgent({
            uri: edge.url,
            proxyTunnel: true,
            requestTls: { ca: readFileSync(edge.caCertPath!) },
        })
    })

    afterEach(async () => {
        await client.close()
        await edge.close()
        rmSync(caDir, { recursive: true, force: true })
    })

    const callWebhook = async (unitId: string, host = WEBHOOK_HOST): Promise<number> => {
        const response = await request(`https://${host}/u/${unitId}/webhook-step`, {
            method: 'POST',
            dispatcher: client,
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ unitId }),
        })
        await response.body.text()
        return response.statusCode
    }

    const callEach = async (unitIds: string[]): Promise<number[]> => {
        const statuses: number[] = []
        for (const unitId of unitIds) {
            statuses.push(await callWebhook(unitId))
        }
        return statuses
    }

    const control = async (method: string, route: string, body?: object): Promise<{ status: number; json: any }> => {
        const response = await internalFetch(`${edge.url}${route}`, {
            method,
            headers: { 'content-type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
        })
        const text = await response.text()
        return { status: response.status, json: text ? parseJSON(text) : undefined }
    }

    const truth = async (): Promise<TruthPage['records']> => (await control('GET', '/_truth')).json.records

    const sendEmail = async (): Promise<number> =>
        (
            await control('POST', '/v2/email/outbound-emails', {
                FromEmailAddress: 'flows@www.example.com',
                Destination: { ToAddresses: ['run-1-9@www.example.com'] },
                Content: { Simple: { Subject: { Data: 'Hello' } } },
            })
        ).status

    it('answers a webhook through the proxy for a client that trusts the edge CA and records its ids', async () => {
        expect(await callWebhook('run-1-1')).toBe(200)

        expect(await truth()).toEqual([
            expect.objectContaining({
                seq: 1,
                kind: 'webhook',
                status: 200,
                unitId: 'run-1-1',
                actionId: 'webhook-step',
                detail: { request: { method: 'POST', host: WEBHOOK_HOST, path: '/u/run-1-1/webhook-step' } },
            }),
        ])
    })

    it.each<[string, object, number[]]>([
        ['a counted dose', { dose: { count: 2 } }, [503, 503, 200, 200]],
        ['a share', { dose: { share: 0.5 } }, [200, 503, 200, 503]],
        [
            'a fault for another host',
            { match: { host: 'other.example.com' }, dose: { share: 1 } },
            [200, 200, 200, 200],
        ],
    ])('answers webhooks with dest.status under %s', async (_name, shape, statuses) => {
        expect(
            (await control('POST', '/_faults', { name: 'dest.status', params: { code: 503 }, ...shape })).status
        ).toBe(201)

        expect(await callEach(['run-1-1', 'run-1-2', 'run-1-3', 'run-1-4'])).toEqual(statuses)
        expect((await truth()).map(({ status, fault }) => [status, fault])).toEqual(
            statuses.map((status) => [status, status === 503 ? 'dest.status' : undefined])
        )
    })

    const ANSWER_503: ValveEntry = {
        valve: 'dest.status',
        target: WEBHOOK_HOST,
        dose: { code: 503, share: 1 },
        at: '0ms',
        for: '1m',
    }

    const startValve = async (entry = ANSWER_503) => {
        const context: ValveContext = {
            environment: {
                actuate: (action) =>
                    action.kind === 'edge.fault'
                        ? Promise.resolve(edge.hold(action.rule))
                        : Promise.reject(new Error(`no ${action.kind} here`)),
            },
            probe: { runningJobs: () => Promise.resolve(0) },
            teams: [],
        }
        const valves = createValves({ pollMs: 5 })
        await valves.start([entry], context)
        await waitForExpect(() => expect(valves.timeline()[0].appliedAt).toBeDefined(), 2000, 5)
        return valves
    }

    it('answers webhooks with the status of a dest.status valve until the valve releases', async () => {
        const valves = await startValve()

        const held = await callWebhook('run-1-1')
        await waitForExpect(() => expect(valves.timeline()[0].observedAt).toBeDefined(), 2000, 5)
        await valves.releaseAll()

        expect({ held, released: await callWebhook('run-1-2'), error: valves.timeline()[0].error }).toEqual({
            held: 503,
            released: 200,
            error: undefined,
        })
    })

    it.each<[string, string, boolean]>([
        ['its hold ends', '100ms', true],
        ['the drive ends', '1m', false],
    ])(
        'ends a dest.status valve no webhook reached as not observed as soon as %s',
        async (_story, holdFor, releasedBeforeDriveEnds) => {
            const valves = await startValve({ ...ANSWER_503, for: holdFor })

            if (releasedBeforeDriveEnds) {
                await waitForExpect(() => expect(valves.timeline()[0].releasedAt).toBeDefined(), 2000, 5)
            }
            await valves.releaseAll()

            expect({ error: valves.timeline()[0].error, next: await callWebhook('run-1-1') }).toEqual({
                error: 'applied but not observed',
                next: 200,
            })
        },
        3000
    )

    it.each<[string, object, () => Promise<number>, () => Promise<number>, number[]]>([
        [
            'keeps a destination fault for the webhook after an SES send',
            { name: 'dest.status', params: { code: 500 }, dose: { count: 1 } },
            sendEmail,
            () => callWebhook('run-1-1'),
            [200, 500],
        ],
        [
            'keeps an SES fault for the SES send after a webhook',
            { name: 'ses.reject', params: { type: 'rejected' }, dose: { count: 1 } },
            () => callWebhook('run-1-1'),
            sendEmail,
            [200, 400],
        ],
    ])('%s', async (_story, fault, first, second, statuses) => {
        await control('POST', '/_faults', fault)

        expect([await first(), await second()]).toEqual(statuses)
    })

    it('answers 502 for a host it does not fake that cannot be reached', async () => {
        const closed = http.createServer()
        await new Promise<void>((resolve) => closed.listen(0, '127.0.0.1', resolve))
        const { port } = closed.address() as AddressInfo
        await new Promise<void>((resolve) => closed.close(() => resolve()))

        await expect(request(`http://127.0.0.1:${port}/elsewhere`, { dispatcher: client })).rejects.toThrow('502')
    })

    it('tunnels a host it does not fake to that host unchanged', async () => {
        const upstream = http.createServer((req, res) => res.end(`upstream saw ${req.method} ${req.url}`))
        await new Promise<void>((resolve) => upstream.listen(0, '127.0.0.1', resolve))
        try {
            const { port } = upstream.address() as AddressInfo
            const response = await request(`http://127.0.0.1:${port}/elsewhere`, { dispatcher: client })

            expect(await response.body.text()).toBe('upstream saw GET /elsewhere')
            expect(await truth()).toEqual([])
        } finally {
            upstream.closeAllConnections()
            await new Promise<void>((resolve) => upstream.close(() => resolve()))
        }
    })
})
