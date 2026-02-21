import { MetricTracker } from './metric-tracker'

describe('MetricTracker', () => {
    it('should store the metric name as given', () => {
        const tracker = new MetricTracker('events', 10, 1000)
        expect(tracker.metricName).toBe('events')
    })

    it('should accumulate multiple records to the same key', () => {
        const tracker = new MetricTracker('events', 10, 1000)
        tracker.record({ team_id: '1' }, 3)
        tracker.record({ team_id: '1' }, 7)
        tracker.record({ team_id: '1' }, 2)

        const entries = tracker.flush()
        expect(entries).toHaveLength(1)
        expect(entries[0].value).toBe(12)
    })

    it('should handle multiple keys independently', () => {
        const tracker = new MetricTracker('events', 10, 1000)
        tracker.record({ team_id: '1' }, 10)
        tracker.record({ team_id: '2' }, 20)

        const entries = tracker.flush()
        expect(entries).toHaveLength(2)
        expect(entries.find((e) => e.key.team_id === '1')?.value).toBe(10)
        expect(entries.find((e) => e.key.team_id === '2')?.value).toBe(20)
    })

    it('should return empty array when no data recorded', () => {
        const tracker = new MetricTracker('events', 10, 1000)
        expect(tracker.flush()).toEqual([])
    })

    it('should clear data after flush', () => {
        const tracker = new MetricTracker('events', 10, 1000)
        tracker.record({ team_id: '1' }, 5)

        tracker.flush()

        expect(tracker.flush()).toEqual([])
    })

    it('should accumulate fresh data after flush', () => {
        const tracker = new MetricTracker('events', 10, 1000)
        tracker.record({ team_id: '1' }, 10)
        tracker.flush()

        tracker.record({ team_id: '1' }, 3)
        const entries = tracker.flush()

        expect(entries).toHaveLength(1)
        expect(entries[0].value).toBe(3)
    })

    it('should deserialize key back to object', () => {
        const tracker = new MetricTracker('events', 10, 1000)
        tracker.record({ team_id: '42', event: '$pageview' }, 1)

        const entries = tracker.flush()
        expect(entries[0].key).toEqual({ team_id: '42', event: '$pageview' })
    })

    describe('top-N selection', () => {
        it.each([
            { numEntries: 5, topN: 3, expectedCount: 3, desc: 'takes top N when more entries than N' },
            { numEntries: 3, topN: 10, expectedCount: 3, desc: 'takes all entries when fewer than N' },
            { numEntries: 10, topN: 1, expectedCount: 1, desc: 'takes only the top entry when N=1' },
        ])('$desc (entries=$numEntries, topN=$topN)', ({ numEntries, topN, expectedCount }) => {
            const tracker = new MetricTracker('metric', topN, 1000)

            for (let i = 0; i < numEntries; i++) {
                tracker.record({ id: String(i) }, i + 1)
            }

            expect(tracker.flush()).toHaveLength(expectedCount)
        })

        it('should select entries with highest values', () => {
            const tracker = new MetricTracker('metric', 2, 1000)
            tracker.record({ id: 'low' }, 1)
            tracker.record({ id: 'high' }, 100)
            tracker.record({ id: 'medium' }, 50)

            const keys = tracker.flush().map((e) => e.key.id)
            expect(keys).toEqual(['high', 'medium'])
        })

        it('should sort entries by value descending', () => {
            const tracker = new MetricTracker('metric', 5, 1000)
            tracker.record({ id: 'a' }, 3)
            tracker.record({ id: 'b' }, 1)
            tracker.record({ id: 'c' }, 5)
            tracker.record({ id: 'd' }, 2)

            const values = tracker.flush().map((e) => e.value)
            expect(values).toEqual([5, 3, 2, 1])
        })
    })

    describe('maxKeys LRU eviction', () => {
        it('should evict least recently used key when maxKeys exceeded', () => {
            const tracker = new MetricTracker('metric', 10, 3)
            tracker.record({ id: 'a' }, 1)
            tracker.record({ id: 'b' }, 1)
            tracker.record({ id: 'c' }, 1)
            tracker.record({ id: 'd' }, 1) // evicts 'a'

            const keys = tracker.flush().map((e) => e.key.id)
            expect(keys).toEqual(expect.arrayContaining(['b', 'c', 'd']))
            expect(keys).not.toContain('a')
        })

        it('should refresh key on record preventing eviction', () => {
            const tracker = new MetricTracker('metric', 10, 3)
            tracker.record({ id: 'a' }, 1)
            tracker.record({ id: 'b' }, 1)
            tracker.record({ id: 'c' }, 1)
            tracker.record({ id: 'a' }, 1) // refreshes 'a', now 'b' is LRU
            tracker.record({ id: 'd' }, 1) // evicts 'b'

            const keys = tracker.flush().map((e) => e.key.id)
            expect(keys).toEqual(expect.arrayContaining(['a', 'c', 'd']))
            expect(keys).not.toContain('b')
        })

        it('should preserve accumulated value when refreshing key', () => {
            const tracker = new MetricTracker('metric', 10, 3)
            tracker.record({ id: 'a' }, 5)
            tracker.record({ id: 'b' }, 1)
            tracker.record({ id: 'c' }, 1)
            tracker.record({ id: 'a' }, 3) // refreshes 'a', value should be 8

            const entries = tracker.flush()
            expect(entries.find((e) => e.key.id === 'a')?.value).toBe(8)
        })

        it('should not evict when under the limit', () => {
            const tracker = new MetricTracker('metric', 10, 5)
            tracker.record({ id: 'a' }, 1)
            tracker.record({ id: 'b' }, 1)
            tracker.record({ id: 'c' }, 1)

            expect(tracker.flush()).toHaveLength(3)
        })
    })
})
