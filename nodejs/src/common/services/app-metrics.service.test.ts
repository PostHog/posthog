import { APP_METRICS_OUTPUT, AppMetricsOutput } from '../../ingestion/common/outputs'
import { IngestionOutputs } from '../../ingestion/outputs/ingestion-outputs'
import { parseJSON } from '../../utils/json-parse'
import { AppMetricInput, AppMetricsService } from './app-metrics.service'

describe('AppMetricsService', () => {
    let queueMessages: jest.Mock<Promise<void>, [string, any[]]>
    let outputs: IngestionOutputs<AppMetricsOutput>

    beforeEach(() => {
        queueMessages = jest.fn().mockResolvedValue(undefined)
        outputs = {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages,
        } as unknown as IngestionOutputs<AppMetricsOutput>
    })

    function input(overrides: Partial<AppMetricInput> = {}): AppMetricInput {
        return {
            team_id: 1,
            app_source: 'hog_function',
            app_source_id: 'fn-1',
            instance_id: 'inst-1',
            metric_kind: 'success',
            metric_name: 'succeeded',
            count: 1,
            ...overrides,
        }
    }

    function getQueuedPayloads(callIndex = 0): Record<string, unknown>[] {
        const messages = queueMessages.mock.calls[callIndex][1]
        return messages.map((m: { value: Buffer }) => parseJSON(m.value.toString()) as Record<string, unknown>)
    }

    describe('dedupe + flush', () => {
        it('flush is a no-op when buffer is empty', async () => {
            const service = new AppMetricsService(outputs)
            await service.flush()
            expect(queueMessages).not.toHaveBeenCalled()
        })

        it('aggregates counts for the same key', async () => {
            const service = new AppMetricsService(outputs)
            service.queueMetric(input({ count: 1 }))
            service.queueMetric(input({ count: 2 }))
            service.queueMetric(input({ count: 4 }))
            await service.flush()

            const payloads = getQueuedPayloads()
            expect(payloads).toHaveLength(1)
            expect(payloads[0].count).toBe(7)
        })

        it.each([
            ['team_id', { team_id: 2 }],
            ['app_source', { app_source: 'hog_flow' }],
            ['app_source_id', { app_source_id: 'fn-2' }],
            ['instance_id', { instance_id: 'inst-2' }],
            ['metric_kind', { metric_kind: 'failure' }],
            ['metric_name', { metric_name: 'failed' }],
        ])('keeps %s separate in the buffer', async (_field, override) => {
            const service = new AppMetricsService(outputs)
            service.queueMetric(input())
            service.queueMetric(input(override as Partial<AppMetricInput>))
            await service.flush()

            expect(getQueuedPayloads()).toHaveLength(2)
        })

        it('treats undefined instance_id as ""', async () => {
            const service = new AppMetricsService(outputs)
            service.queueMetric(input({ instance_id: undefined }))
            service.queueMetric(input({ instance_id: '' }))
            await service.flush()

            const payloads = getQueuedPayloads()
            expect(payloads).toHaveLength(1)
            expect(payloads[0].instance_id).toBe('')
            expect(payloads[0].count).toBe(2)
        })

        it('uses APP_METRICS_OUTPUT and team id as kafka key', async () => {
            const service = new AppMetricsService(outputs)
            service.queueMetric(input({ team_id: 42 }))
            await service.flush()

            expect(queueMessages).toHaveBeenCalledWith(APP_METRICS_OUTPUT, expect.any(Array))
            const messages = queueMessages.mock.calls[0][1] as { key: Buffer }[]
            expect(messages[0].key.toString()).toBe('42')
        })

        it('clears the buffer after flush', async () => {
            const service = new AppMetricsService(outputs)
            service.queueMetric(input())
            await service.flush()
            queueMessages.mockClear()

            await service.flush()
            expect(queueMessages).not.toHaveBeenCalled()
        })

        it('queueMetrics calls queueMetric for each entry', async () => {
            const service = new AppMetricsService(outputs)
            service.queueMetrics([input({ count: 1 }), input({ count: 2 }), input({ team_id: 2, count: 5 })])
            await service.flush()

            const payloads = getQueuedPayloads().sort((a, b) => (a.team_id as number) - (b.team_id as number))
            expect(payloads).toHaveLength(2)
            expect(payloads[0]).toMatchObject({ team_id: 1, count: 3 })
            expect(payloads[1]).toMatchObject({ team_id: 2, count: 5 })
        })
    })

    describe('flush coalescing', () => {
        it('chains a follow-up flush when a flush is already in flight', async () => {
            // Make the underlying produce hang until we resolve it.
            let resolveFirst!: () => void
            queueMessages.mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))

            const service = new AppMetricsService(outputs)
            service.queueMetric(input({ count: 1 }))

            // Start the first flush — it'll hang on the first queueMessages call.
            const first = service.flush()

            // Queue another metric while the first flush is in-flight.
            service.queueMetric(input({ team_id: 2, count: 7 }))

            // Asking to flush again returns a different promise that completes
            // *after* the in-flight one drains the new buffer.
            const second = service.flush()
            expect(second).not.toBe(first)

            // Let the first flush finish.
            resolveFirst()
            await first

            // The chained flush should now drain the second batch.
            await second
            expect(queueMessages).toHaveBeenCalledTimes(2)

            const firstPayloads = getQueuedPayloads(0)
            expect(firstPayloads).toHaveLength(1)
            expect(firstPayloads[0]).toMatchObject({ team_id: 1, count: 1 })

            const secondPayloads = getQueuedPayloads(1)
            expect(secondPayloads).toHaveLength(1)
            expect(secondPayloads[0]).toMatchObject({ team_id: 2, count: 7 })
        })

        it('multiple concurrent flush() callers behind the in-flight flush share one follow-up', async () => {
            let resolveFirst!: () => void
            queueMessages.mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))

            const service = new AppMetricsService(outputs)
            service.queueMetric(input({ count: 1 }))
            const first = service.flush()

            service.queueMetric(input({ team_id: 2, count: 1 }))
            const a = service.flush()
            const b = service.flush()
            expect(a).toBe(b) // both share the single chained follow-up

            resolveFirst()
            await Promise.all([first, a, b])

            // Two underlying produce calls: the original + the single chained one.
            expect(queueMessages).toHaveBeenCalledTimes(2)
        })
    })

    describe('buffer-full trigger', () => {
        it('triggers a background flush once maxBufferSize is reached', async () => {
            const service = new AppMetricsService(outputs, { maxBufferSize: 3 })

            service.queueMetric(input({ app_source_id: 'fn-1' }))
            service.queueMetric(input({ app_source_id: 'fn-2' }))
            expect(queueMessages).not.toHaveBeenCalled()

            // Third unique key crosses the threshold and kicks off a flush.
            service.queueMetric(input({ app_source_id: 'fn-3' }))
            await service.waitForBackpressure()

            expect(queueMessages).toHaveBeenCalledTimes(1)
            expect(getQueuedPayloads()).toHaveLength(3)
        })

        it('does not double-trigger on aggregations within the same key', async () => {
            const service = new AppMetricsService(outputs, { maxBufferSize: 2 })
            service.queueMetric(input({ count: 1 }))
            service.queueMetric(input({ count: 1 })) // same key, no growth
            service.queueMetric(input({ count: 1 })) // still same key
            // Buffer is at size 1 — no flush yet.
            expect(queueMessages).not.toHaveBeenCalled()
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
            new AppMetricsService(outputs)
            expect(jest.getTimerCount()).toBe(0)
        })

        it('drains the buffer on the configured interval', async () => {
            const service = new AppMetricsService(outputs, { backgroundFlushIntervalMs: 100 })
            service.queueMetric(input())

            await jest.advanceTimersByTimeAsync(100)
            expect(queueMessages).toHaveBeenCalledTimes(1)

            service.queueMetric(input({ team_id: 2 }))
            await jest.advanceTimersByTimeAsync(100)
            expect(queueMessages).toHaveBeenCalledTimes(2)

            await service.shutdown()
        })

        it('shutdown stops the background timer', async () => {
            const service = new AppMetricsService(outputs, { backgroundFlushIntervalMs: 100 })
            expect(jest.getTimerCount()).toBe(1)

            await service.shutdown()
            expect(jest.getTimerCount()).toBe(0)
        })
    })

    describe('shutdown', () => {
        it('flushes pending entries on shutdown', async () => {
            const service = new AppMetricsService(outputs)
            service.queueMetric(input())
            await service.shutdown()

            expect(queueMessages).toHaveBeenCalledTimes(1)
            expect(getQueuedPayloads()).toHaveLength(1)
        })

        it('rejects further queueMetric calls after shutdown', async () => {
            const service = new AppMetricsService(outputs)
            await service.shutdown()
            expect(() => service.queueMetric(input())).toThrow(/shutdown/)
        })

        it('is idempotent', async () => {
            const service = new AppMetricsService(outputs)
            service.queueMetric(input())
            await service.shutdown()
            await service.shutdown()
            expect(queueMessages).toHaveBeenCalledTimes(1)
        })

        it('awaits an in-flight flush before resolving', async () => {
            let resolveFirst!: () => void
            queueMessages.mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))

            const service = new AppMetricsService(outputs)
            service.queueMetric(input())
            const flushPromise = service.flush()

            const shutdownPromise = service.shutdown()
            let shutdownResolved = false
            shutdownPromise.then(() => (shutdownResolved = true))

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
            const service = new AppMetricsService(outputs)
            await service.waitForBackpressure()
            // Just shouldn't hang.
        })

        it('waits for the in-flight flush to settle', async () => {
            let resolveFirst!: () => void
            queueMessages.mockImplementationOnce(() => new Promise<void>((r) => (resolveFirst = r)))

            const service = new AppMetricsService(outputs)
            service.queueMetric(input())
            void service.flush()

            const wait = service.waitForBackpressure()
            let resolved = false
            wait.then(() => (resolved = true))

            await new Promise((r) => setImmediate(r))
            expect(resolved).toBe(false)

            resolveFirst()
            await wait
            expect(resolved).toBe(true)
        })

        it('does not throw when the in-flight flush rejects', async () => {
            queueMessages.mockRejectedValueOnce(new Error('boom'))
            const service = new AppMetricsService(outputs)
            service.queueMetric(input())
            const flushed = service.flush().catch(() => undefined)

            // waitForBackpressure should swallow the error.
            await expect(service.waitForBackpressure()).resolves.toBeUndefined()
            await flushed
        })
    })
})
