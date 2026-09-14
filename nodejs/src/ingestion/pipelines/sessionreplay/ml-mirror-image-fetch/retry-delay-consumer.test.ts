import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { RetryDelayMetrics } from './metrics'
import { RetryDelayConsumer } from './retry-delay-consumer'

const NOW_MS = 1_700_000_000_000
const DELAY_MS = 60_000
const FRONTIER = 'session_replay_image_fetch'

function message(timestamp: number | undefined, overrides: Partial<Message> = {}): Message {
    return {
        value: Buffer.from('{"v":1}'),
        key: Buffer.from('example.com'),
        size: 7,
        topic: 'ai_research_session_replay_image_fetch_retry_1m',
        partition: 0,
        offset: 0,
        timestamp,
        ...overrides,
    }
}

interface Harness {
    consumer: RetryDelayConsumer
    produce: jest.Mock<Promise<void>, any[]>
    storeOffsets: jest.Mock<void, [Message[]]>
    heartbeat: jest.Mock<void, []>
}

function build(overrides: { isStopping?: () => boolean; delayMs?: number } = {}): Harness {
    const produce = jest.fn(() => Promise.resolve())
    const storeOffsets = jest.fn()
    const heartbeat = jest.fn()
    const consumer = new RetryDelayConsumer({ produce } as unknown as KafkaProducerWrapper, {
        frontierTopic: FRONTIER,
        delayMs: overrides.delayMs ?? DELAY_MS,
        heartbeat,
        heartbeatIntervalMs: 10_000,
        isStopping: overrides.isStopping,
        storeOffsets,
    })
    return { consumer, produce, storeOffsets, heartbeat }
}

describe('RetryDelayConsumer', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(NOW_MS))
    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it.each([0, -1, Number.NaN])('refuses an invalid delay of %p', (delayMs) => {
        expect(() => build({ delayMs })).toThrow('positive delay')
    })

    it('does nothing for an empty batch', async () => {
        const harness = build()

        await harness.consumer.handleBatch([])

        expect(harness.produce).not.toHaveBeenCalled()
        expect(harness.storeOffsets).not.toHaveBeenCalled()
    })

    it('publishes a ripe batch and stores its offsets once', async () => {
        const harness = build()
        const messages = [message(NOW_MS - DELAY_MS, { offset: 1 }), message(NOW_MS - DELAY_MS, { offset: 2 })]

        await harness.consumer.handleBatch(messages)

        expect(harness.produce).toHaveBeenCalledTimes(2)
        expect(harness.produce.mock.calls[0][0]).toMatchObject({
            topic: FRONTIER,
            key: messages[0].key,
            value: messages[0].value,
        })
        expect(harness.storeOffsets).toHaveBeenCalledTimes(1)
        expect(harness.storeOffsets).toHaveBeenCalledWith(messages)
    })

    it('waits once for the newest append timestamp in the batch', async () => {
        const harness = build()
        const older = message(NOW_MS - 30_000, { offset: 1 })
        const newer = message(NOW_MS - 10_000, { offset: 2 })

        const handled = harness.consumer.handleBatch([older, newer])
        await jest.advanceTimersByTimeAsync(30_000)
        expect(harness.produce).not.toHaveBeenCalled()
        await jest.advanceTimersByTimeAsync(20_000)
        await handled

        expect(harness.produce).toHaveBeenCalledTimes(2)
        expect(harness.storeOffsets).toHaveBeenCalledTimes(1)
    })

    it('reports health while a batch is deliberately waiting', async () => {
        const harness = build()

        const handled = harness.consumer.handleBatch([message(NOW_MS)])
        await jest.advanceTimersByTimeAsync(DELAY_MS)
        await handled

        expect(harness.heartbeat).toHaveBeenCalledTimes(7)
    })

    it.each([undefined, Number.NaN, 0, -1])(
        'throws for an invalid broker append timestamp of %p',
        async (timestamp) => {
            const harness = build()
            const incReleased = jest.spyOn(RetryDelayMetrics, 'incReleased')

            await expect(harness.consumer.handleBatch([message(timestamp)])).rejects.toThrow(
                'requires broker append timestamps'
            )
            expect(incReleased).toHaveBeenCalledWith('invalid_timestamp', 1)
            expect(harness.produce).not.toHaveBeenCalled()
            expect(harness.storeOffsets).not.toHaveBeenCalled()
        }
    )

    it('throws and stores no offset when any frontier publish fails', async () => {
        const harness = build()
        harness.produce.mockRejectedValueOnce(new Error('broker unavailable'))

        await expect(harness.consumer.handleBatch([message(NOW_MS - DELAY_MS)])).rejects.toThrow(
            'could not publish a record back to the frontier'
        )
        expect(harness.storeOffsets).not.toHaveBeenCalled()
    })

    it('stops publishing the batch after the first frontier failure', async () => {
        const harness = build()
        harness.produce.mockResolvedValueOnce().mockRejectedValueOnce(new Error('broker unavailable'))
        const messages = [
            message(NOW_MS - DELAY_MS, { offset: 1 }),
            message(NOW_MS - DELAY_MS, { offset: 2 }),
            message(NOW_MS - DELAY_MS, { offset: 3 }),
        ]

        await expect(harness.consumer.handleBatch(messages)).rejects.toThrow(
            'could not publish a record back to the frontier'
        )

        expect(harness.produce).toHaveBeenCalledTimes(2)
        expect(harness.storeOffsets).not.toHaveBeenCalled()
    })

    it('stores the batch offset after it skips a malformed record', async () => {
        const harness = build()
        const malformed = message(NOW_MS - DELAY_MS, { value: null })

        await harness.consumer.handleBatch([malformed])

        expect(harness.produce).not.toHaveBeenCalled()
        expect(harness.storeOffsets).toHaveBeenCalledWith([malformed])
    })

    it('abandons the batch without storing offsets when shutdown has started', async () => {
        const harness = build({ isStopping: () => true })

        await harness.consumer.handleBatch([message(NOW_MS)])

        expect(harness.produce).not.toHaveBeenCalled()
        expect(harness.storeOffsets).not.toHaveBeenCalled()
    })

    it('abandons an active wait when shutdown starts', async () => {
        let stopping = false
        const harness = build({ isStopping: () => stopping })
        const handled = harness.consumer.handleBatch([message(NOW_MS)])

        await jest.advanceTimersByTimeAsync(10_000)
        stopping = true
        await jest.advanceTimersByTimeAsync(10_000)
        await handled

        expect(harness.produce).not.toHaveBeenCalled()
        expect(harness.storeOffsets).not.toHaveBeenCalled()
    })
})
