import { IngestionOutput } from '../../ingestion/outputs/ingestion-output'
import { parseJSON } from '../../utils/json-parse'
import { AggregatingProducer } from './aggregating-producer'

interface TestItem {
    key: string
    count: number
    label?: string
}

function makeOutput(): IngestionOutput & { queueMessagesMock: jest.Mock<Promise<void>, [any[]]> } {
    const queueMessagesMock = jest.fn().mockResolvedValue(undefined)
    return {
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: queueMessagesMock,
        checkHealth: jest.fn().mockResolvedValue(undefined),
        checkTopicExists: jest.fn().mockResolvedValue(undefined),
        queueMessagesMock,
    } as unknown as IngestionOutput & { queueMessagesMock: jest.Mock<Promise<void>, [any[]]> }
}

const baseOptions = {
    key: (item: TestItem) => item.key,
    merge: (existing: TestItem, incoming: TestItem) => ({
        ...existing,
        count: existing.count + incoming.count,
    }),
    serialize: (item: TestItem) => Buffer.from(JSON.stringify(item)),
}

describe('AggregatingProducer', () => {
    let output: ReturnType<typeof makeOutput>

    beforeEach(() => {
        output = makeOutput()
    })

    function getQueuedItems(callIndex = 0): TestItem[] {
        const messages = output.queueMessagesMock.mock.calls[callIndex][0]
        return messages.map((m: { value: Buffer }) => parseJSON(m.value.toString()) as TestItem)
    }

    describe('aggregation', () => {
        it('flush is a no-op when buffer is empty', async () => {
            const producer = new AggregatingProducer(output, baseOptions)
            await producer.flush()
            expect(output.queueMessagesMock).not.toHaveBeenCalled()
        })

        it('merges items sharing a key', async () => {
            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            producer.queue({ key: 'a', count: 2 })
            producer.queue({ key: 'a', count: 4 })
            await producer.flush()

            const items = getQueuedItems()
            expect(items).toHaveLength(1)
            expect(items[0]).toEqual({ key: 'a', count: 7 })
        })

        it('keeps distinct keys separate', async () => {
            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            producer.queue({ key: 'b', count: 2 })
            await producer.flush()

            expect(getQueuedItems()).toHaveLength(2)
        })

        it('uses the merge function (last write does not win by default)', async () => {
            const producer = new AggregatingProducer(output, {
                ...baseOptions,
                merge: (e, i) => ({ ...e, count: e.count + i.count, label: i.label ?? e.label }),
            })
            producer.queue({ key: 'a', count: 1, label: 'first' })
            producer.queue({ key: 'a', count: 2, label: 'second' })
            await producer.flush()

            expect(getQueuedItems()[0]).toEqual({ key: 'a', count: 3, label: 'second' })
        })

        it('produces with key=null', async () => {
            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            await producer.flush()

            const messages = output.queueMessagesMock.mock.calls[0][0]
            expect(messages[0].key).toBeNull()
        })

        it('clears the buffer after flush', async () => {
            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            await producer.flush()
            output.queueMessagesMock.mockClear()

            await producer.flush()
            expect(output.queueMessagesMock).not.toHaveBeenCalled()
        })
    })

    describe('flush coalescing', () => {
        it('chains a follow-up flush behind an in-flight flush', async () => {
            let resolveFirst!: () => void
            output.queueMessagesMock.mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))

            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })

            const first = producer.flush()
            producer.queue({ key: 'b', count: 2 })

            const second = producer.flush()
            expect(second).not.toBe(first)

            resolveFirst()
            await first
            await second

            expect(output.queueMessagesMock).toHaveBeenCalledTimes(2)
            expect(getQueuedItems(0)).toEqual([{ key: 'a', count: 1 }])
            expect(getQueuedItems(1)).toEqual([{ key: 'b', count: 2 }])
        })

        it('multiple flush callers behind the in-flight share one follow-up', async () => {
            let resolveFirst!: () => void
            output.queueMessagesMock.mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))

            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            const first = producer.flush()

            producer.queue({ key: 'b', count: 1 })
            const a = producer.flush()
            const b = producer.flush()
            expect(a).toBe(b)

            resolveFirst()
            await Promise.all([first, a, b])
            expect(output.queueMessagesMock).toHaveBeenCalledTimes(2)
        })
    })

    describe('buffer-full trigger', () => {
        it('triggers a background flush at maxBufferSize', async () => {
            const producer = new AggregatingProducer(output, { ...baseOptions, maxBufferSize: 3 })
            producer.queue({ key: 'a', count: 1 })
            producer.queue({ key: 'b', count: 1 })
            expect(output.queueMessagesMock).not.toHaveBeenCalled()

            producer.queue({ key: 'c', count: 1 })
            await producer.waitForBackpressure()

            expect(output.queueMessagesMock).toHaveBeenCalledTimes(1)
            expect(getQueuedItems()).toHaveLength(3)
        })

        it('does not double-trigger on aggregations within the same key', () => {
            const producer = new AggregatingProducer(output, { ...baseOptions, maxBufferSize: 2 })
            producer.queue({ key: 'a', count: 1 })
            producer.queue({ key: 'a', count: 1 })
            producer.queue({ key: 'a', count: 1 })
            expect(output.queueMessagesMock).not.toHaveBeenCalled()
        })
    })

    describe('background flush', () => {
        beforeEach(() => {
            jest.useFakeTimers()
        })
        afterEach(() => {
            jest.useRealTimers()
        })

        it('does not start a timer when backgroundFlushIntervalMs is unset', () => {
            new AggregatingProducer(output, baseOptions)
            expect(jest.getTimerCount()).toBe(0)
        })

        it('drains the buffer on the configured interval', async () => {
            const producer = new AggregatingProducer(output, { ...baseOptions, backgroundFlushIntervalMs: 100 })
            producer.queue({ key: 'a', count: 1 })

            await jest.advanceTimersByTimeAsync(100)
            expect(output.queueMessagesMock).toHaveBeenCalledTimes(1)

            producer.queue({ key: 'b', count: 1 })
            await jest.advanceTimersByTimeAsync(100)
            expect(output.queueMessagesMock).toHaveBeenCalledTimes(2)

            await producer.shutdown()
        })

        it('shutdown stops the background timer', async () => {
            const producer = new AggregatingProducer(output, { ...baseOptions, backgroundFlushIntervalMs: 100 })
            expect(jest.getTimerCount()).toBe(1)

            await producer.shutdown()
            expect(jest.getTimerCount()).toBe(0)
        })
    })

    describe('shutdown', () => {
        it('flushes pending entries on shutdown', async () => {
            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            await producer.shutdown()

            expect(output.queueMessagesMock).toHaveBeenCalledTimes(1)
        })

        it('rejects further queue calls after shutdown', async () => {
            const producer = new AggregatingProducer(output, baseOptions)
            await producer.shutdown()
            expect(() => producer.queue({ key: 'a', count: 1 })).toThrow(/shutdown/)
        })

        it('is idempotent', async () => {
            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            await producer.shutdown()
            await producer.shutdown()
            expect(output.queueMessagesMock).toHaveBeenCalledTimes(1)
        })

        it('awaits an in-flight flush before resolving', async () => {
            let resolveFirst!: () => void
            output.queueMessagesMock.mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))

            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            const flushPromise = producer.flush()

            const shutdownPromise = producer.shutdown()
            let shutdownResolved = false
            void shutdownPromise.then(() => (shutdownResolved = true))

            await new Promise((r) => setImmediate(r))
            expect(shutdownResolved).toBe(false)

            resolveFirst()
            await flushPromise
            await shutdownPromise
            expect(shutdownResolved).toBe(true)
        })
    })

    describe('waitForBackpressure', () => {
        it('resolves immediately when no flush is in flight', async () => {
            const producer = new AggregatingProducer(output, baseOptions)
            await producer.waitForBackpressure()
        })

        it('waits for the in-flight flush to settle', async () => {
            let resolveFirst!: () => void
            output.queueMessagesMock.mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))

            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            void producer.flush()

            const wait = producer.waitForBackpressure()
            let resolved = false
            void wait.then(() => (resolved = true))

            await new Promise((r) => setImmediate(r))
            expect(resolved).toBe(false)

            resolveFirst()
            await wait
            expect(resolved).toBe(true)
        })

        it('does not throw when the in-flight flush rejects', async () => {
            output.queueMessagesMock.mockRejectedValueOnce(new Error('boom'))
            const producer = new AggregatingProducer(output, baseOptions)
            producer.queue({ key: 'a', count: 1 })
            const flushed = producer.flush().catch(() => undefined)

            await expect(producer.waitForBackpressure()).resolves.toBeUndefined()
            await flushed
        })
    })
})
