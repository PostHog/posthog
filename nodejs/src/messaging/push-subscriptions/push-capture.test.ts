import { IncomingMessage, Server, createServer } from 'http'
import { AddressInfo } from 'net'

import { parseJSON } from '~/common/utils/json-parse'

import { PushCaptureService } from './push-capture'

describe('PushCaptureService', () => {
    let server: Server
    let base: string
    let received: { url: string; headers: IncomingMessage['headers']; body: any }[]
    let status: number

    beforeEach(async () => {
        received = []
        status = 200
        server = createServer((req, res) => {
            const chunks: Buffer[] = []
            req.on('data', (chunk) => chunks.push(chunk))
            req.on('end', () => {
                received.push({
                    url: req.url ?? '',
                    headers: req.headers,
                    body: parseJSON(Buffer.concat(chunks).toString('utf8')),
                })
                res.writeHead(status, { 'Content-Type': 'application/json' }).end('{}')
            })
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    })

    afterEach(async () => {
        await new Promise((resolve) => server.close(resolve))
    })

    const send = (): Promise<void> =>
        new PushCaptureService(base).capture({
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

    it.each([[400], [401], [429], [500], [503]])('throws on a %s so the SDK is not told it stored', async (code) => {
        status = code

        await expect(send()).rejects.toThrow(`capture returned ${code}`)
    })
})
