import { FeedOrderSentinel } from './feed-order-sentinel'
import { SerializedKafkaMessage } from './types'

function msg(offset: number, overrides: Partial<SerializedKafkaMessage> = {}): SerializedKafkaMessage {
    return {
        topic: 'events',
        partition: 0,
        offset,
        timestamp: 0,
        key: null,
        value: null,
        headers: { token: 't', distinct_id: 'a' },
        ...overrides,
    }
}

describe('FeedOrderSentinel', () => {
    it('passes messages fed in ascending offset order per key', () => {
        const sentinel = new FeedOrderSentinel()
        expect(sentinel.check([msg(1), msg(2)], 'c1', false)).toEqual({ outOfOrder: 0, replayed: 0 })
        expect(sentinel.check([msg(3)], 'c1', false)).toEqual({ outOfOrder: 0, replayed: 0 })
    })

    it('flags an offset regression within one consumer incarnation', () => {
        const sentinel = new FeedOrderSentinel()
        sentinel.check([msg(5)], 'c1', false)
        expect(sentinel.check([msg(3)], 'c1', false)).toEqual({ outOfOrder: 1, replayed: 0 })
    })

    it('counts a regression in a replay request as replayed, not a violation', () => {
        const sentinel = new FeedOrderSentinel()
        sentinel.check([msg(5)], 'c1', false)
        expect(sentinel.check([msg(5)], 'c1', true)).toEqual({ outOfOrder: 0, replayed: 1 })
    })

    it('rebaselines when the consumer incarnation changes', () => {
        const sentinel = new FeedOrderSentinel()
        sentinel.check([msg(100)], 'c1', false)
        // A restarted consumer replays from the last commit — not a violation.
        expect(sentinel.check([msg(50)], 'c2', false)).toEqual({ outOfOrder: 0, replayed: 0 })
        // But the new incarnation is now the baseline.
        expect(sentinel.check([msg(40)], 'c2', false)).toEqual({ outOfOrder: 1, replayed: 0 })
    })

    it('tracks keys independently across partitions and distinct_ids', () => {
        const sentinel = new FeedOrderSentinel()
        sentinel.check(
            [msg(10), msg(10, { partition: 1 }), msg(10, { headers: { token: 't', distinct_id: 'b' } })],
            'c1',
            false
        )
        // Same offsets again on other keys don't interfere; only 'a' on partition 0 regresses.
        expect(sentinel.check([msg(9)], 'c1', false)).toEqual({ outOfOrder: 1, replayed: 0 })
        expect(sentinel.check([msg(11, { partition: 1 })], 'c1', false)).toEqual({ outOfOrder: 0, replayed: 0 })
    })

    it('skips messages without routing headers', () => {
        const sentinel = new FeedOrderSentinel()
        const result = sentinel.check([msg(5, { headers: {} }), msg(1, { headers: {} })], 'c1', false)
        expect(result).toEqual({ outOfOrder: 0, replayed: 0 })
        expect(sentinel.size).toBe(0)
    })

    it('evicts the least-recently-seen key at capacity and rebaselines it silently', () => {
        const sentinel = new FeedOrderSentinel(2)
        sentinel.check([msg(10)], 'c1', false)
        sentinel.check([msg(10, { headers: { token: 't', distinct_id: 'b' } })], 'c1', false)
        sentinel.check([msg(10, { headers: { token: 't', distinct_id: 'c' } })], 'c1', false)
        expect(sentinel.size).toBe(2)
        // 'a' was evicted: its regression rebaselines instead of firing.
        expect(sentinel.check([msg(5)], 'c1', false)).toEqual({ outOfOrder: 0, replayed: 0 })
    })
})
