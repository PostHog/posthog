import { IncomingMessage, Server, createServer } from 'http'
import { AddressInfo } from 'net'

import { parseJSON } from '~/common/utils/json-parse'

import { PushCaptureService } from './push-capture'

describe('PushCaptureService', () => {
    let server: Server
    let base: string
    let received: { url: string; headers: IncomingMessage['headers']; body: any }[]
    let status: number
    // Answers taken in order, one per request; `status` answers once they run out.
    let script: { status: number; result?: string; delayMs?: number }[]

    beforeEach(async () => {
        received = []
        status = 200
        script = []
        server = createServer((req, res) => {
            const chunks: Buffer[] = []
            req.on('data', (chunk) => chunks.push(chunk))
            req.on('end', () => {
                received.push({
                    url: req.url ?? '',
                    headers: req.headers,
                    body: parseJSON(Buffer.concat(chunks).toString('utf8')),
                })
                const step = script.shift() ?? { status }
                const uuid = received[received.length - 1].body?.batch?.[0]?.uuid
                const body = step.result ? JSON.stringify({ results: { [uuid]: { result: step.result } } }) : '{}'
                const reply = (): void => {
                    res.writeHead(step.status, { 'Content-Type': 'application/json' }).end(body)
                }
                if (step.delayMs) {
                    setTimeout(reply, step.delayMs)
                } else {
                    reply()
                }
            })
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    })

    afterEach(async () => {
        await new Promise((resolve) => server.close(resolve))
    })

    const send = (timeoutMs = 2000): Promise<void> =>
        new PushCaptureService(base, timeoutMs, () => Promise.resolve()).capture({
            token: 'phc_real',
            event: '$set',
            distinctId: 'user-1',
            properties: { $set: { $device_push_subscription_app: 'cipher' }, $process_person_profile: true },
        })

    it('posts the v1 internal batch envelope django posts', async () => {
        await send()

        expect(received).toHaveLength(1)
        expect(received[0].url).toEqual('/i/v1/analytics/events')
        expect(received[0].body).toMatchObject({
            capture_internal: true,
            historical_migration: false,
            batch: [
                {
                    event: '$set',
                    distinct_id: 'user-1',
                    properties: { $set: { $device_push_subscription_app: 'cipher' } },
                    options: { process_person_profile: true },
                },
            ],
        })
    })

    it('authenticates with the project token, which the endpoint requires', async () => {
        await send()

        expect(received[0].headers.authorization).toEqual('Bearer phc_real')
    })

    it('lifts the legacy person-processing property out of properties', async () => {
        // Left in `properties` it is ingested as an ordinary event property and the option never
        // applies, so the person profile is not processed and the subscription is not stored.
        await send()

        expect(received[0].body.batch[0].properties.$process_person_profile).toBeUndefined()
        expect(received[0].body.batch[0].options.process_person_profile).toEqual(true)
    })

    it('gives every event its own uuid', async () => {
        await send()
        await send()

        expect(received[0].body.batch[0].uuid).not.toEqual(received[1].body.batch[0].uuid)
    })

    it.each([
        ['a client error', 400, 1],
        ['an auth error', 401, 1],
        ['a rate limit, which django does not retry either', 429, 1],
        ['a server error that persists', 500, 4],
        ['an unavailable capture that persists', 503, 4],
    ])('throws on %s so the SDK is not told it stored', async (_name, code, requests) => {
        status = code

        await expect(send()).rejects.toThrow(`capture returned ${code}`)
        expect(received).toHaveLength(requests)
    })

    it.each([
        ['a transient server error', [{ status: 503 }, { status: 200 }], 2],
        [
            'an event capture asked to retry',
            [
                { status: 200, result: 'retry' },
                { status: 200, result: 'ok' },
            ],
            2,
        ],
    ])('stores the registration after %s, as django does', async (_name, steps, requests) => {
        script = steps

        await send()

        expect(received).toHaveLength(requests)
        expect(new Set(received.map((request) => request.body.batch[0].uuid)).size).toEqual(1)
    })

    it('marks each resubmission of an event capture asked to retry', async () => {
        script = [
            { status: 200, result: 'retry' },
            { status: 200, result: 'ok' },
        ]

        await send()

        expect(received.map((request) => request.headers['posthog-attempt'])).toEqual(['1', '2'])
    })

    it('gives up when capture asks to retry on every attempt', async () => {
        script = Array.from({ length: 4 }, () => ({ status: 200, result: 'retry' }))

        await expect(send()).rejects.toThrow('capture asked to retry the event on every attempt')
        expect(received).toHaveLength(4)
    })

    it('does not retry a timeout, which would hold the SDK request for several timeouts', async () => {
        script = [{ status: 200, delayMs: 500 }]

        await expect(send(50)).rejects.toThrow()
        expect(received).toHaveLength(1)
    })
})
