import { parseJSON } from '../../utils/json-parse'
import { TopHog, TopHogOptions } from './tophog'

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

    function createOptions(overrides: Partial<TopHogOptions> = {}): TopHogOptions {
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

    describe('increment and flush', () => {
        it('should produce a single message for one metric/key', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('events.count', { team_id: '42' }, 5)

            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
            expect(getProducedMessages()).toEqual([
                {
                    timestamp: '2025-01-15T10:30:00.000Z',
                    metric: 'events.count',
                    key: { team_id: '42' },
                    value: 5,
                    pipeline: 'test_pipeline',
                    lane: 'test_lane',
                    labels: {},
                },
            ])
        })

        it('should accumulate multiple increments to the same key', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('events.count', { team_id: '1' }, 3)
            tophog.increment('events.count', { team_id: '1' }, 7)
            tophog.increment('events.count', { team_id: '1' }, 2)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages).toHaveLength(1)
            expect(messages[0].value).toBe(12)
        })

        it('should default increment value to 1', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('events.count', { team_id: '1' })
            tophog.increment('events.count', { team_id: '1' })

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages[0].value).toBe(2)
        })

        it('should handle multiple metrics independently', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('events.count', { team_id: '1' }, 10)
            tophog.increment('events.time_ms', { team_id: '1' }, 500)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages).toHaveLength(2)
            expect(messages.find((m) => m.metric === 'events.count')?.value).toBe(10)
            expect(messages.find((m) => m.metric === 'events.time_ms')?.value).toBe(500)
        })

        it('should not produce when there is no data', async () => {
            const tophog = new TopHog(createOptions())

            await tophog.flush()

            expect(mockQueueMessages).not.toHaveBeenCalled()
        })

        it('should include labels in flushed messages', async () => {
            const tophog = new TopHog(createOptions({ labels: { hostname: 'worker-1', region: 'us-east' } }))
            tophog.increment('events.count', { team_id: '1' }, 1)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages[0].labels).toEqual({ hostname: 'worker-1', region: 'us-east' })
        })
    })

    describe('top-N selection', () => {
        it.each([
            { numEntries: 5, topN: 3, expectedCount: 3, desc: 'takes top N when more entries than N' },
            { numEntries: 3, topN: 10, expectedCount: 3, desc: 'takes all entries when fewer than N' },
            { numEntries: 10, topN: 1, expectedCount: 1, desc: 'takes only the top entry when N=1' },
        ])('$desc (entries=$numEntries, topN=$topN)', async ({ numEntries, topN, expectedCount }) => {
            const tophog = new TopHog(createOptions({ defaultTopN: topN }))

            for (let i = 0; i < numEntries; i++) {
                tophog.increment('metric', { id: String(i) }, i + 1)
            }

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages).toHaveLength(expectedCount)
        })

        it('should select entries with highest values', async () => {
            const tophog = new TopHog(createOptions({ defaultTopN: 2 }))
            tophog.increment('metric', { id: 'low' }, 1)
            tophog.increment('metric', { id: 'high' }, 100)
            tophog.increment('metric', { id: 'medium' }, 50)

            await tophog.flush()

            const messages = getProducedMessages()
            const keys = messages.map((m) => m.key.id)
            expect(keys).toEqual(['high', 'medium'])
        })

        it('should sort entries by value descending', async () => {
            const tophog = new TopHog(createOptions({ defaultTopN: 5 }))
            tophog.increment('metric', { id: 'a' }, 3)
            tophog.increment('metric', { id: 'b' }, 1)
            tophog.increment('metric', { id: 'c' }, 5)
            tophog.increment('metric', { id: 'd' }, 2)

            await tophog.flush()

            const values = getProducedMessages().map((m) => m.value)
            expect(values).toEqual([5, 3, 2, 1])
        })
    })

    describe('reset after flush', () => {
        it('should clear counters after flush', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('metric', { id: 'k' }, 10)

            await tophog.flush()
            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should accumulate fresh data after flush', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('metric', { id: 'k' }, 10)
            await tophog.flush()

            tophog.increment('metric', { id: 'k' }, 3)
            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledTimes(2)
            const secondFlushMessages = mockQueueMessages.mock.calls[1][0].messages.map((m: any) => parseJSON(m.value))
            expect(secondFlushMessages[0].value).toBe(3)
        })
    })

    describe('start and stop', () => {
        it('should flush periodically after start', async () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 1000 }))
            tophog.start()

            tophog.increment('metric', { id: 'k' }, 1)
            jest.advanceTimersByTime(1000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)

            tophog.increment('metric', { id: 'k' }, 2)
            jest.advanceTimersByTime(1000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(2)

            await tophog.stop()
        })

        it('should perform a final flush on stop', async () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 60_000 }))
            tophog.start()
            tophog.increment('metric', { id: 'k' }, 5)

            await tophog.stop()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should not flush periodically after stop', async () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 1000 }))
            tophog.start()
            await tophog.stop()

            tophog.increment('metric', { id: 'k' }, 1)
            jest.advanceTimersByTime(5000)

            // Only the final flush from stop(), not the periodic one
            expect(mockQueueMessages).toHaveBeenCalledTimes(0)
        })

        it('should not start multiple intervals', () => {
            const tophog = new TopHog(createOptions({ flushIntervalMs: 1000 }))
            tophog.start()
            tophog.start()

            tophog.increment('metric', { id: 'k' }, 1)
            jest.advanceTimersByTime(1000)

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should work without calling start (manual flush only)', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('metric', { id: 'k' }, 1)

            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })

        it('should flush on stop even if start was never called', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('metric', { id: 'k' }, 1)

            await tophog.stop()

            expect(mockQueueMessages).toHaveBeenCalledTimes(1)
        })
    })

    describe('maxKeys LRU eviction', () => {
        it('should evict least recently used key when instance maxKeys is exceeded', async () => {
            const tophog = new TopHog(createOptions({ maxKeys: 3 }))
            tophog.increment('metric', { id: 'a' }, 1)
            tophog.increment('metric', { id: 'b' }, 1)
            tophog.increment('metric', { id: 'c' }, 1)
            tophog.increment('metric', { id: 'd' }, 1) // evicts 'a'

            await tophog.flush()

            const keys = getProducedMessages().map((m) => m.key.id)
            expect(keys).toEqual(expect.arrayContaining(['b', 'c', 'd']))
            expect(keys).not.toContain('a')
        })

        it('should evict least recently used key when per-metric maxKeys is exceeded', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('metric', { id: 'a' }, 1, 2)
            tophog.increment('metric', { id: 'b' }, 1, 2)
            tophog.increment('metric', { id: 'c' }, 1, 2) // evicts 'a'

            await tophog.flush()

            const keys = getProducedMessages().map((m) => m.key.id)
            expect(keys).toEqual(expect.arrayContaining(['b', 'c']))
            expect(keys).not.toContain('a')
        })

        it('should per-metric maxKeys override instance maxKeys', async () => {
            const tophog = new TopHog(createOptions({ maxKeys: 10 }))
            tophog.increment('metric', { id: 'a' }, 1, 2)
            tophog.increment('metric', { id: 'b' }, 1, 2)
            tophog.increment('metric', { id: 'c' }, 1, 2) // evicts 'a' (per-metric limit of 2)

            await tophog.flush()

            const keys = getProducedMessages().map((m) => m.key.id)
            expect(keys).not.toContain('a')
            expect(keys).toHaveLength(2)
        })

        it('should refresh key on increment preventing eviction', async () => {
            const tophog = new TopHog(createOptions({ maxKeys: 3 }))
            tophog.increment('metric', { id: 'a' }, 1)
            tophog.increment('metric', { id: 'b' }, 1)
            tophog.increment('metric', { id: 'c' }, 1)
            tophog.increment('metric', { id: 'a' }, 1) // refreshes 'a', now 'b' is LRU
            tophog.increment('metric', { id: 'd' }, 1) // evicts 'b'

            await tophog.flush()

            const keys = getProducedMessages().map((m) => m.key.id)
            expect(keys).toEqual(expect.arrayContaining(['a', 'c', 'd']))
            expect(keys).not.toContain('b')
        })

        it('should preserve accumulated value when refreshing key', async () => {
            const tophog = new TopHog(createOptions({ maxKeys: 3 }))
            tophog.increment('metric', { id: 'a' }, 5)
            tophog.increment('metric', { id: 'b' }, 1)
            tophog.increment('metric', { id: 'c' }, 1)
            tophog.increment('metric', { id: 'a' }, 3) // refreshes 'a', value should be 8

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages.find((m) => m.key.id === 'a')?.value).toBe(8)
        })

        it('should not evict when under the limit', async () => {
            const tophog = new TopHog(createOptions({ maxKeys: 5 }))
            tophog.increment('metric', { id: 'a' }, 1)
            tophog.increment('metric', { id: 'b' }, 1)
            tophog.increment('metric', { id: 'c' }, 1)

            await tophog.flush()

            expect(getProducedMessages()).toHaveLength(3)
        })

        it('should not limit when maxKeys is not set', async () => {
            const tophog = new TopHog(createOptions())
            for (let i = 0; i < 100; i++) {
                tophog.increment('metric', { id: String(i) }, 1)
            }

            await tophog.flush()

            expect(getProducedMessages()).toHaveLength(10) // limited by defaultTopN, not maxKeys
        })
    })

    describe('message format', () => {
        it('should include pipeline and lane in every message', async () => {
            const tophog = new TopHog(createOptions({ pipeline: 'analytics', lane: 'heatmap' }))
            tophog.increment('metric', { id: 'k' }, 1)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages[0].pipeline).toBe('analytics')
            expect(messages[0].lane).toBe('heatmap')
        })

        it('should produce to the configured topic', async () => {
            const tophog = new TopHog(createOptions({ topic: 'clickhouse_tophog' }))
            tophog.increment('metric', { id: 'k' }, 1)

            await tophog.flush()

            expect(mockQueueMessages).toHaveBeenCalledWith(expect.objectContaining({ topic: 'clickhouse_tophog' }))
        })

        it('should serialize key as object in flushed messages', async () => {
            const tophog = new TopHog(createOptions())
            tophog.increment('metric', { team_id: '42', event: '$pageview' }, 1)

            await tophog.flush()

            const messages = getProducedMessages()
            expect(messages[0].key).toEqual({ team_id: '42', event: '$pageview' })
        })
    })
})
