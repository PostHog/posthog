import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { RetryDelayConsumer } from './retry-delay-consumer'

const FRONTIER = 'session_replay_image_fetch'
const DELAY_MS = 60_000

function message(overrides: Partial<Message> = {}): Message {
    return {
        value: Buffer.from('{"v":1,"urls":[]}'),
        key: Buffer.from('example.com'),
        size: 17,
        topic: 'session_replay_image_fetch_retry_1m',
        partition: 0,
        offset: 0,
        ...overrides,
    }
}

/** Narrow to what the consumer calls, so a test needs no cast and a new call has to be added here. */
type ProducerCall = { topic: string; key?: Buffer | null; value: Buffer | null }

function fakeProducer(): { produced: ProducerCall[]; producer: KafkaProducerWrapper; fail: () => void } {
    const produced: ProducerCall[] = []
    let failing = false
    const producer = {
        produce: (call: ProducerCall) => {
            if (failing) {
                return Promise.reject(new Error('broker down'))
            }
            produced.push(call)
            return Promise.resolve()
        },
    } as unknown as KafkaProducerWrapper
    return { produced, producer, fail: () => (failing = true) }
}

describe('RetryDelayConsumer', () => {
    it.each([[0], [-1], [NaN]])('refuses to start with a delay of %p', (delayMs) => {
        // The delay is what this consumer exists to apply. A zero or a NaN would republish at once
        // and turn the retry into a hot loop against the site that just failed.
        const { producer } = fakeProducer()

        expect(
            () => new RetryDelayConsumer(producer, { frontierTopic: FRONTIER, delayMs, heartbeat: () => {} })
        ).toThrow('positive delay')
    })

    it('publishes a record whose wait has already passed, without waiting again', async () => {
        // Requirement: the wait is measured from when the record was written. A consumer that
        // restarts must not begin the period again, or a record could wait for ever.
        const { produced, producer } = fakeProducer()
        const consumer = new RetryDelayConsumer(producer, {
            frontierTopic: FRONTIER,
            delayMs: DELAY_MS,
            heartbeat: () => {},
        })

        const startedAt = Date.now()
        await consumer.handleBatch([message({ timestamp: Date.now() - DELAY_MS - 1000 })])

        expect(Date.now() - startedAt).toBeLessThan(1000)
        expect(produced).toHaveLength(1)
        expect(produced[0].topic).toBe(FRONTIER)
    })

    it('keeps the record and its key unchanged', async () => {
        // The record already carries its hop budget and its earliest fetch time, and the key is the
        // registrable domain that decides which consumer owns it. Rewriting either would move the
        // URL to the wrong back queue or hand it a budget it did not earn.
        const { produced, producer } = fakeProducer()
        const consumer = new RetryDelayConsumer(producer, {
            frontierTopic: FRONTIER,
            delayMs: DELAY_MS,
            heartbeat: () => {},
        })
        const original = message({
            timestamp: Date.now() - DELAY_MS - 1,
            value: Buffer.from('{"v":1,"hopsRemaining":7}'),
        })

        await consumer.handleBatch([original])

        expect(produced[0].value?.toString()).toBe('{"v":1,"hopsRemaining":7}')
        expect(produced[0].key?.toString()).toBe('example.com')
    })

    it('beats the heartbeat repeatedly while it waits, not only at the end', async () => {
        // The health check fails a consumer silent for 60 seconds, and these waits run to an hour.
        // One beat after the wait would not save the pod. It has to beat throughout.
        let beats = 0
        const { producer } = fakeProducer()
        const consumer = new RetryDelayConsumer(producer, {
            frontierTopic: FRONTIER,
            delayMs: 60,
            heartbeatIntervalMs: 5,
            heartbeat: () => beats++,
        })

        await consumer.handleBatch([message({ timestamp: Date.now() })])

        // Six or more intervals fit in the wait. Anything above two proves it beat during it.
        expect(beats).toBeGreaterThan(2)
    })

    it('drops a record it cannot publish rather than holding the ones behind it', async () => {
        // Retrying here would hold every record behind this one for another whole period. The URL
        // has no crawl history entry, so a later session offers it again.
        const { produced, producer, fail } = fakeProducer()
        fail()
        const consumer = new RetryDelayConsumer(producer, {
            frontierTopic: FRONTIER,
            delayMs: DELAY_MS,
            heartbeat: () => {},
        })

        await expect(consumer.handleBatch([message({ timestamp: Date.now() - DELAY_MS - 1 })])).resolves.toBeUndefined()

        expect(produced).toHaveLength(0)
    })

    it.each([
        ['no value', { value: null }],
        ['no key', { key: null }],
    ])('drops a record with %s', async (_name, overrides) => {
        const { produced, producer } = fakeProducer()
        const consumer = new RetryDelayConsumer(producer, {
            frontierTopic: FRONTIER,
            delayMs: DELAY_MS,
            heartbeat: () => {},
        })

        await consumer.handleBatch([message({ timestamp: Date.now() - DELAY_MS - 1, ...overrides })])

        expect(produced).toHaveLength(0)
    })

    it('waits the whole period when the record carries no timestamp', async () => {
        // librdkafka reports an absent timestamp as -1, which is not nullish. Reading it as a real
        // time would put the write in 1970 and release every record at once.
        const { producer } = fakeProducer()
        const consumer = new RetryDelayConsumer(producer, {
            frontierTopic: FRONTIER,
            delayMs: 40,
            heartbeat: () => {},
        })

        const startedAt = Date.now()
        await consumer.handleBatch([message({ timestamp: -1 })])

        expect(Date.now() - startedAt).toBeGreaterThanOrEqual(30)
    })
})
