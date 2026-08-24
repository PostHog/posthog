import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { RetryDelayConsumer } from './retry-delay-consumer'

const DELAY_MS = 60_000
const FRONTIER = 'session_replay_image_fetch'

function message(writtenAtMs: number, overrides: Partial<Message> = {}): Message {
    return {
        value: Buffer.from('{"v":1}'),
        key: Buffer.from('example.com'),
        size: 7,
        topic: 'session_replay_image_fetch_retry_1m',
        partition: 0,
        offset: 0,
        timestamp: writtenAtMs,
        ...overrides,
    }
}

function build(overrides: { isStopping?: () => boolean; produce?: () => Promise<void>; delayMs?: number } = {}): {
    consumer: RetryDelayConsumer
    published: string[]
    stored: number[]
    beats: () => number
} {
    const published: string[] = []
    const stored: number[] = []
    let beats = 0
    const producer = {
        produce: async ({ topic }: { topic: string }) => {
            await (overrides.produce?.() ?? Promise.resolve())
            published.push(topic)
        },
    } as unknown as KafkaProducerWrapper
    const consumer = new RetryDelayConsumer(producer, {
        frontierTopic: FRONTIER,
        delayMs: overrides.delayMs ?? DELAY_MS,
        heartbeat: () => beats++,
        heartbeatIntervalMs: 1,
        storeOffset: (m) => stored.push(m.offset),
        isStopping: overrides.isStopping,
    })
    return { consumer, published, stored, beats: () => beats }
}

describe('RetryDelayConsumer', () => {
    it('publishes a record whose period has already passed, without waiting', async () => {
        const { consumer, published, stored } = build()

        await consumer.handleBatch([message(Date.now() - DELAY_MS - 1000)])

        expect(published).toEqual([FRONTIER])
        expect(stored).toEqual([0])
    })

    it('waits out what is left of the period, measured from when the record was written', async () => {
        // A consumer that restarts must not begin the wait again, or a record could be held for
        // several periods by a rolling deploy.
        const { consumer, published, beats } = build()

        await consumer.handleBatch([message(Date.now() - DELAY_MS + 20)])

        expect(published).toEqual([FRONTIER])
        expect(beats()).toBeGreaterThan(0)
    })

    it('waits no longer than the period of its topic, whatever the record timestamp says', async () => {
        // The timestamp comes from whichever pod wrote the record. A clock ahead of this one would
        // otherwise hold the record for longer than the tier it is in.
        const { consumer, published } = build({ delayMs: 50 })

        const startedAt = Date.now()
        await consumer.handleBatch([message(Date.now() + 60 * 60 * 1000, { offset: 1 })])

        expect(published).toEqual([FRONTIER])
        expect(Date.now() - startedAt).toBeLessThan(DELAY_MS)
    })

    it('abandons a record when the pod is shutting down before the wait starts', async () => {
        const { consumer, published, stored } = build({ isStopping: () => true })

        await consumer.handleBatch([message(Date.now())])

        expect(published).toEqual([])
        expect(stored).toEqual([])
    })

    it('gives up a wait in progress rather than finishing it', async () => {
        // A record with a full period left would otherwise hold a rolling deploy for that period,
        // until Kubernetes killed the pod. The offset stays uncommitted, so the next pod reads the
        // record and waits out what remains.
        let stopping = false
        const { consumer, published, stored } = build({ isStopping: () => stopping })
        setTimeout(() => (stopping = true), 20)

        const startedAt = Date.now()
        await consumer.handleBatch([message(Date.now())])
        const elapsed = Date.now() - startedAt

        expect(published).toEqual([])
        expect(stored).toEqual([])
        // The record had the whole period left. Returning anywhere near it means the wait ran on.
        expect(elapsed).toBeLessThan(DELAY_MS / 10)
    })

    it('fails the batch for a record it could not publish, so no later offset commits past it', async () => {
        // Storing nothing is not enough on its own. The next poll would read the records after this
        // one and store one of their offsets, and an offset is a high water mark.
        const { consumer, published, stored } = build({
            produce: () => Promise.reject(new Error('broker down')),
        })

        await expect(consumer.handleBatch([message(Date.now() - DELAY_MS - 1000)])).rejects.toThrow(
            'could not publish a record back to the frontier'
        )

        expect(published).toEqual([])
        expect(stored).toEqual([])
    })

    it('stores the offset of a record it can never publish, so the partition still moves', async () => {
        const { consumer, published, stored } = build()

        await consumer.handleBatch([message(Date.now() - DELAY_MS - 1000, { offset: 7, value: null })])

        expect(published).toEqual([])
        expect(stored).toEqual([7])
    })

    it('stores each offset as it goes, so a shutdown keeps only the records it did not reach', async () => {
        // Requirement 21. The consumer that owns this one stores offsets for a whole batch once the
        // handler returns, so anything left unstored here must stay unstored there.
        let releasedSoFar = 0
        const { consumer, published, stored } = build({
            produce: () => Promise.resolve(releasedSoFar++).then(() => {}),
            isStopping: () => releasedSoFar >= 2,
        })
        const ripe = Date.now() - DELAY_MS - 1000

        await consumer.handleBatch([
            message(ripe, { offset: 4 }),
            message(ripe, { offset: 5 }),
            message(ripe, { offset: 6 }),
        ])

        expect(published).toEqual([FRONTIER, FRONTIER])
        expect(stored).toEqual([4, 5])
    })

    it.each([[0], [-1], [NaN]])('refuses to start with a delay of %p', (delayMs) => {
        const producer = {} as KafkaProducerWrapper

        expect(
            () =>
                new RetryDelayConsumer(producer, {
                    frontierTopic: FRONTIER,
                    delayMs,
                    heartbeat: () => {},
                    storeOffset: () => {},
                })
        ).toThrow('positive delay')
    })
})
