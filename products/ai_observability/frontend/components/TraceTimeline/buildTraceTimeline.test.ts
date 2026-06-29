import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { buildTraceTimeline } from './buildTraceTimeline'

function ev(id: string, isoOffsetMs: number, latencySec: number, extra: Record<string, any> = {}): LLMTraceEvent {
    return {
        id,
        event: '$ai_generation',
        createdAt: new Date(1_000_000_000_000 + isoOffsetMs).toISOString(),
        properties: { $ai_latency: latencySec, ...extra },
    }
}

describe('buildTraceTimeline', () => {
    it('positions bars by timestamp offset and latency', () => {
        const { bars, totalMs, laneCount } = buildTraceTimeline([ev('a', 0, 1), ev('b', 2000, 0.5)])
        expect(bars).toHaveLength(2)
        expect(bars[0]).toMatchObject({ id: 'a', startMs: 0, durationMs: 1000, lane: 0 })
        expect(bars[1]).toMatchObject({ id: 'b', startMs: 2000, durationMs: 500, lane: 0 })
        expect(totalMs).toBe(2500)
        expect(laneCount).toBe(1) // sequential, non-overlapping → one lane
    })

    it('stacks overlapping (nested) events into separate lanes', () => {
        // a generation 0–2000ms containing a span 500–1000ms — they overlap in time
        const { bars, laneCount } = buildTraceTimeline([
            ev('gen', 0, 2),
            ev('span', 500, 0.5, { $ai_span_name: 'tool', event: '$ai_span' }),
        ])
        expect(bars[0]).toMatchObject({ startMs: 0, durationMs: 2000 })
        expect(bars[1]).toMatchObject({ startMs: 500, durationMs: 500 })
        expect(bars[0].lane).not.toBe(bars[1].lane)
        expect(laneCount).toBe(2)
    })

    it('marks error events', () => {
        const { bars } = buildTraceTimeline([ev('a', 0, 1, { $ai_is_error: true })])
        expect(bars[0].isError).toBe(true)
    })

    it('falls back to sequential layout when timestamps have no spread', () => {
        // both events share the same createdAt — lay them out back-to-back by latency
        const { bars, totalMs, laneCount } = buildTraceTimeline([ev('a', 0, 1), ev('b', 0, 2)])
        expect(bars[0]).toMatchObject({ startMs: 0, durationMs: 1000 })
        expect(bars[1]).toMatchObject({ startMs: 1000, durationMs: 2000 })
        expect(totalMs).toBe(3000)
        expect(laneCount).toBe(1) // back-to-back, no overlap → one lane
    })

    it('caps each label to the room before the next bar in its lane', () => {
        const seq = buildTraceTimeline([ev('a', 0, 1), ev('b', 2000, 0.5)])
        expect(seq.bars[0].labelRoomMs).toBe(2000) // up to b's start
        expect(seq.bars[1].labelRoomMs).toBe(500) // last in lane → up to the trace end (2500 - 2000)

        // Bars in different lanes don't shorten each other's room.
        const nested = buildTraceTimeline([ev('gen', 0, 2), ev('span', 500, 0.5)])
        expect(nested.bars[0].labelRoomMs).toBe(2000) // gen alone in lane 0 → trace end
        expect(nested.bars[1].labelRoomMs).toBe(1500) // span alone in lane 1 → trace end (2000 - 500)
    })

    it('returns empty for no events', () => {
        expect(buildTraceTimeline([])).toEqual({ bars: [], totalMs: 0, laneCount: 0 })
    })
})
