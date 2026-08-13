import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { RetryDelayConsumer } from './retry-delay-consumer'

const DELAY_MS = 60_000
const FRONTIER = 'session_replay_image_fetch'

function message(writtenAtMs: number, key = 'example.com'): Message {
    return {
        value: Buffer.from('{"v":1}'),
        key: Buffer.from(key),
        size: 7,
        topic: 'session_replay_image_fetch_retry_1m',
        partition: 0,
        offset: 0,
        timestamp: writtenAtMs,
    }
}

function build(overrides: { isStopping?: () => boolean } = {}): {
    consumer: RetryDelayConsumer
    published: string[]
    beats: () => number
} {
    const published: string[] = []
    let beats = 0
    const producer = {
        produce: ({ topic }: { topic: string }) => {
            published.push(topic)
            return Promise.resolve()
        },
    } as unknown as KafkaProducerWrapper
    const consumer = new RetryDelayConsumer(producer, {
        frontierTopic: FRONTIER,
        delayMs: DELAY_MS,
        heartbeat: () => beats++,
        heartbeatIntervalMs: 1,
        ...overrides,
    })
    return { consumer, published, beats: () => beats }
}

describe('RetryDelayConsumer', () => {
    it('publishes a record whose period has already passed, without waiting', async () => {
        const { consumer, published } = build()

        await consumer.handleBatch([message(Date.now() - DELAY_MS - 1000)])

        expect(published).toEqual([FRONTIER])
    })

    it('waits out what is left of the period, measured from when the record was written', async () => {
        // A consumer that restarts must not begin the wait again, or a record could be held for
        // several periods by a rolling deploy.
        const { consumer, published, beats } = build()

        await consumer.handleBatch([message(Date.now() - DELAY_MS + 20)])

        expect(published).toEqual([FRONTIER])
        // It slept rather than publishing at once, and said it was alive while it did.
        expect(beats()).toBeGreaterThan(0)
    })

    it('abandons a record when the pod is shutting down before the wait starts', async () => {
        const { consumer, published } = build({ isStopping: () => true })

        await consumer.handleBatch([message(Date.now())])

        expect(published).toEqual([])
    })

    it('gives up a wait in progress rather than finishing it', async () => {
        // The point is promptness. A record with a full period left would otherwise hold a rolling
        // deploy for that period, until Kubernetes killed the pod. The offset is uncommitted, so
        // the next pod reads it and waits out whatever remains.
        let stopping = false
        const { consumer, published } = build({ isStopping: () => stopping })
        setTimeout(() => (stopping = true), 20)

        const startedAt = Date.now()
        await consumer.handleBatch([message(Date.now())])
        const elapsed = Date.now() - startedAt

        expect(published).toEqual([])
        // The record had the whole period left. Returning anywhere near it means the wait ran on.
        expect(elapsed).toBeLessThan(DELAY_MS / 10)
    })

    it.each([[0], [-1], [NaN]])('refuses to start with a delay of %p', (delayMs) => {
        const producer = {} as KafkaProducerWrapper

        expect(
            () =>
                new RetryDelayConsumer(producer, {
                    frontierTopic: FRONTIER,
                    delayMs,
                    heartbeat: () => {},
                })
        ).toThrow('positive delay')
    })
})
