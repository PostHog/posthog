import { parseJSON } from '../../utils/json-parse'
import { TopHog, TopHogOptionalConfig, TopHogRequiredConfig } from './tophog'

describe('TopHog', () => {
    let mockQueueMessages: jest.Mock
    let mockProducer: { queueMessages: jest.Mock }

    beforeEach(() => {
        jest.useFakeTimers({ now: new Date('2025-01-15T10:30:00.000Z') })
        mockQueueMessages = jest.fn().mockResolvedValue(undefined)
        mockProducer = { queueMessages: mockQueueMessages }
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    function createOptions(
        overrides: Partial<TopHogRequiredConfig & TopHogOptionalConfig> = {}
    ): TopHogRequiredConfig & Partial<TopHogOptionalConfig> {
        return {
            kafkaProducer: mockProducer as any,
            topic: 'test_tophog',
            pipeline: 'test_pipeline',
            lane: 'test_lane',
            ...overrides,
        }
    }

    function getProducedMessages(): any[] {
        if (mockQueueMessages.mock.calls.length === 0) {
            return []
        }
        return mockQueueMessages.mock.calls.flatMap((call: any) => call[0].messages.map((m: any) => parseJSON(m.value)))
    }

    describe('tracker registry', () => {
        it('should return the same tracker instance for the same name', () => {
            const tophog = new TopHog(createOptions())
            const a = tophog.register('events')
            const b = tophog.register('events')
            expect(a).toBe(b)
        })

        it('should return different tracker instances for different names', () => {
            const tophog = new TopHog(createOptions())
            const a = tophog.register('events')
            const b = tophog.register('heatmaps')
            expect(a).not.toBe(b)
        })

        it('should store metric name as given', () => {
            const tophog = new TopHog(createOptions())
            expect(tophog.register('events').metricName).toBe('events')
            expect(tophog.register('latency').metricName).toBe('latency')
        })

        it('should return the same average tracker instance for the same name', () => {
            const tophog = new TopHog(createOptions())
            const a = tophog.registerAverage('latency')
            const b = tophog.registerAverage('latency')
            expect(a).toBe(b)
        })
    })

    describe('flush collects from all trackers', () => {
        it('should produce messages from trackers', async () => {
            const tophog = new TopHog(createOptions())
            tophog.register('events').record({ team_id: '42' }, 5)

            await tophog.flush()

            expect(getProducedMessages()).toEqual([
                {
                    timestamp: '2025-01-15T10:30:00.000Z',
                    metric: 'events',
                    key: { team_id: '42' },
                    value: 5,
                    pipeline: 'test_pipeline',
                    lane: 'test_lane',
                    labels: {},
                },
            ])
        })

        it('should collect entries from multiple trackers in a single flush', async () => {
            const tophog = new TopHog(createOptions())
            tophog.register('events').record({ team_id: '1' }, 10)
            tophog.register('latency').record({ team_id: '1' }, 500)
            tophog.register('heatmaps').record({ team_id: '2' }, 3)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages).toHaveLength(3)
            expect(messages.find((m) => m.metric === 'events')?.value).toBe(10)
            expect(messages.find((m) => m.metric === 'latency')?.value).toBe(500)
            expect(messages.find((m) => m.metric === 'heatmaps')?.value).toBe(3)
        })

        it('should not produce when there is no data', async () => {
            const tophog = new TopHog(createOptions())

            await tophog.flush()

            expect(mockQueueMessages).not.toHaveBeenCalled()
        })

        it('should clear all trackers after flush', async () => {
            const tophog = new TopHog(createOptions())
            tophog.register('events').record({ team_id: '1' }, 10)

            await tophog.flush()
            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should include labels in flushed messages', async () => {
            const tophog = new TopHog(createOptions({ labels: { hostname: 'worker-1', region: 'us-east' } }))
            tophog.register('events').record({ team_id: '1' }, 1)

            await tophog.flush()

            expect(getProducedMessages()[0].labels).toEqual({ hostname: 'worker-1', region: 'us-east' })
        })

        it('should include pipeline and lane in every message', async () => {
            const tophog = new TopHog(createOptions({ pipeline: 'analytics', lane: 'heatmap' }))
            tophog.register('events').record({ team_id: '1' }, 1)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages[0].pipeline).toBe('analytics')
            expect(messages[0].lane).toBe('heatmap')
        })

        it('should produce to the configured topic', async () => {
            const tophog = new TopHog(createOptions({ topic: 'clickhouse_tophog' }))
            tophog.register('events').record({ team_id: '1' }, 1)

            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledWith(expect.objectContaining({ topic: 'clickhouse_tophog' }))
        })
    })

    describe('start and stop', () => {
        it('should flush periodically after start', async () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 1000 }))
            tophog.start()

            tophog.register('metric').record({ id: 'k' }, 1)
            jest.advanceTimersByTime(1000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)

            tophog.register('metric').record({ id: 'k' }, 2)
            jest.advanceTimersByTime(1000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(2)

            await tophog.stop()
        })

        it('should perform a final flush on stop', async () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 60_000 }))
            tophog.start()
            tophog.register('metric').record({ id: 'k' }, 5)

            await tophog.stop()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should not flush periodically after stop', async () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 1000 }))
            tophog.start()
            await tophog.stop()

            tophog.register('metric').record({ id: 'k' }, 1)
            jest.advanceTimersByTime(5000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(0)
        })

        it('should not start multiple intervals', () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 1000 }))
            tophog.start()
            tophog.start()

            tophog.register('metric').record({ id: 'k' }, 1)
            jest.advanceTimersByTime(1000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should work without calling start (manual flush only)', async () => {
            const tophog = new TopHog(createOptions())
            tophog.register('metric').record({ id: 'k' }, 1)

            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should flush on stop even if start was never called', async () => {
            const tophog = new TopHog(createOptions())
            tophog.register('metric').record({ id: 'k' }, 1)

            await tophog.stop()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })
    })
})
