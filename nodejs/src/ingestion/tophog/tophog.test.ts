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
        it('should return the same sum tracker instance for the same name', () => {
            const tophog = new TopHog(createOptions())
            const a = tophog.registerSum('events')
            const b = tophog.registerSum('events')
            expect(a).toBe(b)
        })

        it('should return different tracker instances for different names', () => {
            const tophog = new TopHog(createOptions())
            const a = tophog.registerSum('events')
            const b = tophog.registerSum('heatmaps')
            expect(a).not.toBe(b)
        })

        it('should store metric name as given', () => {
            const tophog = new TopHog(createOptions())
            expect(tophog.registerSum('events').metricName).toBe('events')
            expect(tophog.registerSum('latency').metricName).toBe('latency')
        })

        it('should return the same average tracker instance for the same name', () => {
            const tophog = new TopHog(createOptions())
            const a = tophog.registerAverage('latency')
            const b = tophog.registerAverage('latency')
            expect(a).toBe(b)
        })

        it('should return the same max tracker instance for the same name', () => {
            const tophog = new TopHog(createOptions())
            const a = tophog.registerMax('max_size')
            const b = tophog.registerMax('max_size')
            expect(a).toBe(b)
        })

        it('should return independent trackers for the same name across different types', () => {
            const tophog = new TopHog(createOptions())
            const sum = tophog.registerSum('latency')
            const max = tophog.registerMax('latency')
            const avg = tophog.registerAverage('latency')
            expect(sum).not.toBe(max)
            expect(sum).not.toBe(avg)
            expect(max).not.toBe(avg)
        })
    })

    describe('flush collects from all trackers', () => {
        it('should produce messages from trackers', async () => {
            const tophog = new TopHog(createOptions())
            tophog.registerSum('events').record({ team_id: '42' }, 5)

            await tophog.flush()

            expect(getProducedMessages()).toEqual([
                {
                    timestamp: '2025-01-15T10:30:00.000Z',
                    metric: 'events',
                    type: 'sum',
                    key: { team_id: '42' },
                    value: 5,
                    count: 1,
                    pipeline: 'test_pipeline',
                    lane: 'test_lane',
                    labels: {},
                },
            ])
        })

        it('should include type=sum for sum trackers', async () => {
            const tophog = new TopHog(createOptions())
            tophog.registerSum('events').record({ team_id: '1' }, 5)

            await tophog.flush()

            const msg = getProducedMessages()[0]
            expect(msg.type).toBe('sum')
            expect(msg.value).toBe(5)
            expect(msg.count).toBe(1)
        })

        it('should include type=max for max trackers', async () => {
            const tophog = new TopHog(createOptions())
            tophog.registerMax('max_size').record({ team_id: '1' }, 100)

            await tophog.flush()

            const msg = getProducedMessages()[0]
            expect(msg.type).toBe('max')
            expect(msg.value).toBe(100)
            expect(msg.count).toBe(1)
        })

        it('should include type=avg for average trackers', async () => {
            const tophog = new TopHog(createOptions())
            const tracker = tophog.registerAverage('latency')
            tracker.record({ team_id: '1' }, 10)
            tracker.record({ team_id: '1' }, 30)

            await tophog.flush()

            const msg = getProducedMessages()[0]
            expect(msg.type).toBe('avg')
            expect(msg.value).toBe(20)
            expect(msg.count).toBe(2)
        })

        it('should collect entries from mixed tracker types in a single flush', async () => {
            const tophog = new TopHog(createOptions())
            tophog.registerSum('events').record({ team_id: '1' }, 10)
            tophog.registerMax('max_size').record({ team_id: '1' }, 500)
            tophog.registerAverage('avg_latency').record({ team_id: '1' }, 30)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages).toHaveLength(3)
            expect(messages.find((m) => m.metric === 'events')).toMatchObject({ type: 'sum', value: 10 })
            expect(messages.find((m) => m.metric === 'max_size')).toMatchObject({ type: 'max', value: 500 })
            expect(messages.find((m) => m.metric === 'avg_latency')).toMatchObject({ type: 'avg', value: 30 })
        })

        it('should flush same-named metrics across different types independently', async () => {
            const tophog = new TopHog(createOptions())
            tophog.registerSum('latency').record({ team_id: '1' }, 10)
            tophog.registerSum('latency').record({ team_id: '1' }, 20)
            tophog.registerMax('latency').record({ team_id: '1' }, 10)
            tophog.registerMax('latency').record({ team_id: '1' }, 20)
            tophog.registerAverage('latency').record({ team_id: '1' }, 10)
            tophog.registerAverage('latency').record({ team_id: '1' }, 20)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages).toHaveLength(3)
            expect(messages.find((m) => m.type === 'sum')).toMatchObject({ metric: 'latency', value: 30, count: 2 })
            expect(messages.find((m) => m.type === 'max')).toMatchObject({ metric: 'latency', value: 20, count: 2 })
            expect(messages.find((m) => m.type === 'avg')).toMatchObject({ metric: 'latency', value: 15, count: 2 })
        })

        it('should not produce when there is no data', async () => {
            const tophog = new TopHog(createOptions())

            await tophog.flush()

            expect(mockQueueMessages).not.toHaveBeenCalled()
        })

        it('should clear all trackers after flush', async () => {
            const tophog = new TopHog(createOptions())
            tophog.registerSum('events').record({ team_id: '1' }, 10)

            await tophog.flush()
            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should include labels in flushed messages', async () => {
            const tophog = new TopHog(createOptions({ labels: { hostname: 'worker-1', region: 'us-east' } }))
            tophog.registerSum('events').record({ team_id: '1' }, 1)

            await tophog.flush()

            expect(getProducedMessages()[0].labels).toEqual({ hostname: 'worker-1', region: 'us-east' })
        })

        it('should include pipeline and lane in every message', async () => {
            const tophog = new TopHog(createOptions({ pipeline: 'analytics', lane: 'heatmap' }))
            tophog.registerSum('events').record({ team_id: '1' }, 1)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages[0].pipeline).toBe('analytics')
            expect(messages[0].lane).toBe('heatmap')
        })

        it('should produce to the configured topic', async () => {
            const tophog = new TopHog(createOptions({ topic: 'clickhouse_tophog' }))
            tophog.registerSum('events').record({ team_id: '1' }, 1)

            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledWith(expect.objectContaining({ topic: 'clickhouse_tophog' }))
        })
    })

    describe('start and stop', () => {
        it('should flush periodically after start', async () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 1000 }))
            tophog.start()

            tophog.registerSum('metric').record({ id: 'k' }, 1)
            jest.advanceTimersByTime(1000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)

            tophog.registerSum('metric').record({ id: 'k' }, 2)
            jest.advanceTimersByTime(1000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(2)

            await tophog.stop()
        })

        it('should perform a final flush on stop', async () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 60_000 }))
            tophog.start()
            tophog.registerSum('metric').record({ id: 'k' }, 5)

            await tophog.stop()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should not flush periodically after stop', async () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 1000 }))
            tophog.start()
            await tophog.stop()

            tophog.registerSum('metric').record({ id: 'k' }, 1)
            jest.advanceTimersByTime(5000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(0)
        })

        it('should not start multiple intervals', () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 1000 }))
            tophog.start()
            tophog.start()

            tophog.registerSum('metric').record({ id: 'k' }, 1)
            jest.advanceTimersByTime(1000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should work without calling start (manual flush only)', async () => {
            const tophog = new TopHog(createOptions())
            tophog.registerSum('metric').record({ id: 'k' }, 1)

            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should flush on stop even if start was never called', async () => {
            const tophog = new TopHog(createOptions())
            tophog.registerSum('metric').record({ id: 'k' }, 1)

            await tophog.stop()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })
    })
})
