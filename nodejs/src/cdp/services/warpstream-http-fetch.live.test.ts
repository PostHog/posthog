import { Producer } from 'node-rdkafka'

import { WarpstreamHttpFetchService } from './warpstream-http-fetch.service'

/**
 * Live integration test for WarpstreamHttpFetchService against a real
 * Warpstream Agent playground (see the `warpstream` service in
 * docker-compose.dev.yml). Validates the production HTTP fetch contract —
 * request body shape, base64 record encoding, and round-trip from
 * (partition, offset) — which the unit tests can only mock.
 *
 * Opt-in: only runs when WARPSTREAM_LIVE_AGENT_URL is set, so it stays
 * out of the default CI matrix. Local invocation:
 *
 *   docker compose -f docker-compose.dev.yml --profile warpstream up -d warpstream
 *   WARPSTREAM_LIVE_AGENT_URL=http://localhost:18080 \
 *   WARPSTREAM_LIVE_KAFKA_BROKERS=localhost:19092 \
 *   pnpm exec jest --forceExit src/cdp/services/warpstream-http-fetch.live.test.ts
 */
const AGENT_URL = process.env.WARPSTREAM_LIVE_AGENT_URL
const KAFKA_BROKERS = process.env.WARPSTREAM_LIVE_KAFKA_BROKERS ?? 'localhost:19092'

const liveDescribe = AGENT_URL ? describe : describe.skip

liveDescribe('WarpstreamHttpFetchService (live agent)', () => {
    jest.setTimeout(60_000)

    const topic = `warpstream-fetch-live-${Date.now()}`

    interface ProducedRef {
        partition: number
        offset: number
        value: Buffer
    }

    // Produce each message via `opaque` so the delivery-report carries the
    // original value back — the rdkafka driver doesn't reliably round-trip
    // `report.value` with acks=all on Warpstream.
    const produce = (messages: { key: string; value: Buffer }[]): Promise<ProducedRef[]> =>
        new Promise((resolve, reject) => {
            const producer = new Producer({
                'metadata.broker.list': KAFKA_BROKERS,
                dr_cb: true,
            })
            const refs: ProducedRef[] = []
            let pollTimer: NodeJS.Timeout | null = null
            producer.on('event.error', reject)
            producer.on('ready', () => {
                pollTimer = setInterval(() => producer.poll(), 200)
                for (const m of messages) {
                    producer.produce(topic, null, m.value, m.key, Date.now(), m.value)
                }
            })
            producer.on('delivery-report', (err, report) => {
                if (err) {
                    if (pollTimer) {
                        clearInterval(pollTimer)
                    }
                    return reject(err)
                }
                refs.push({
                    partition: report.partition,
                    offset: Number(report.offset),
                    value: report.opaque as Buffer,
                })
                if (refs.length === messages.length) {
                    if (pollTimer) {
                        clearInterval(pollTimer)
                    }
                    producer.flush(5000, () => producer.disconnect(() => resolve(refs)))
                }
            })
            producer.connect()
        })

    it('round-trips a record through produce → /v1/kafka/fetch → decoded value', async () => {
        const fetcher = new WarpstreamHttpFetchService({ url: AGENT_URL!, username: '', password: '' })

        const value = Buffer.from(JSON.stringify({ hello: 'warpstream', when: Date.now() }))
        const [ref] = await produce([{ key: 'k1', value }])

        // Poll the agent — playground batches produces and may not have indexed
        // the record by the time `produce` returns its delivery report.
        let got: Buffer | undefined
        const deadline = Date.now() + 10_000
        while (Date.now() < deadline && !got) {
            const out = await fetcher.fetchRecords(topic, [{ partition: ref.partition, offset: ref.offset }])
            got = out.get(`${ref.partition}:${ref.offset}`)
            if (!got) {
                await new Promise((r) => setTimeout(r, 250))
            }
        }

        expect(got).toBeDefined()
        expect(got!.toString('utf8')).toBe(value.toString('utf8'))
    })

    it('batches multiple refs into a single fetch and returns each by partition:offset', async () => {
        const fetcher = new WarpstreamHttpFetchService({ url: AGENT_URL!, username: '', password: '' })

        const values = [
            Buffer.from(JSON.stringify({ idx: 0 })),
            Buffer.from(JSON.stringify({ idx: 1 })),
            Buffer.from(JSON.stringify({ idx: 2 })),
        ]
        const refs = await produce(values.map((v, i) => ({ key: `k-${i}`, value: v })))

        // Warpstream batches produces and updates high_watermark asynchronously —
        // poll the fetch endpoint until every ref resolves rather than relying on
        // a fixed sleep. 10s ceiling is well above the agent's normal flush window.
        let out = new Map<string, Buffer>()
        const deadline = Date.now() + 10_000
        while (Date.now() < deadline) {
            out = await fetcher.fetchRecords(
                topic,
                refs.map((r) => ({ partition: r.partition, offset: r.offset }))
            )
            if (refs.every((r) => out.has(`${r.partition}:${r.offset}`))) {
                break
            }
            await new Promise((r) => setTimeout(r, 250))
        }

        for (const r of refs) {
            const got = out.get(`${r.partition}:${r.offset}`)
            expect(got?.toString('utf8')).toBe(r.value.toString('utf8'))
        }
    })

    it('returns an empty map for refs that point past the high watermark', async () => {
        const fetcher = new WarpstreamHttpFetchService({ url: AGENT_URL!, username: '', password: '' })

        const out = await fetcher.fetchRecords(topic, [{ partition: 0, offset: 999_999 }])
        expect(out.size).toBe(0)
    })
})
