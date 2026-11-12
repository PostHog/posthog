import http from 'http'
import { AddressInfo } from 'net'
import { PostHog } from 'posthog-node'
import { gunzipSync } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'

export interface FakePostHogEvent {
    event: string
    distinctId: string
    properties: Record<string, unknown>
}

export interface FakePostHog {
    client: PostHog
    events: FakePostHogEvent[]
    close(): Promise<void>
}

export async function startFakePostHog(): Promise<FakePostHog> {
    const events: FakePostHogEvent[] = []
    const server = http.createServer((req, res) => {
        const chunks: Buffer[] = []
        req.on('data', (chunk: Buffer) => chunks.push(chunk))
        req.on('end', () => {
            const raw = Buffer.concat(chunks)
            const body = parseJSON(
                (req.headers['content-encoding'] === 'gzip' ? gunzipSync(raw) : raw).toString() || '{}'
            )
            for (const message of body.batch ?? []) {
                events.push({ event: message.event, distinctId: message.distinct_id, properties: message.properties })
            }
            res.writeHead(200, { 'content-type': 'application/json' })
            res.end('{"status":1}')
        })
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo
    const client = new PostHog('phc_fake_posthog', {
        host: `http://127.0.0.1:${port}`,
        flushAt: 1,
        flushInterval: 0,
        disableGeoip: true,
    })

    return {
        client,
        events,
        close: async () => {
            await client.shutdown()
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        },
    }
}
