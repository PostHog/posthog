import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { buildTicks, buildTraceTimeline, formatDuration } from './buildTraceTimeline'

const T0 = 1_000_000_000_000

function ev(
    id: string,
    event: string,
    atMs: number,
    latencySec?: number,
    props: Record<string, any> = {}
): LLMTraceEvent {
    return {
        id,
        event,
        createdAt: new Date(T0 + atMs).toISOString(),
        properties: {
            $ai_trace_id: 't1',
            ...(latencySec !== undefined ? { $ai_latency: latencySec } : {}),
            ...props,
        },
    }
}

describe('buildTraceTimeline', () => {
    it('nests SDK events (createdAt = operation end) under their parents, one lane per depth', () => {
        // Root trace ends at 3000ms, the agent span inside it at 2800ms, the
        // generation inside that at 1500ms — each bar must start latency before it.
        const { bars, totalMs, laneCount } = buildTraceTimeline([
            ev('root', '$ai_trace', 3000, 3, { $ai_span_id: 't1' }),
            ev('agent', '$ai_span', 2800, 2.5, { $ai_span_id: 's1', $ai_parent_id: 't1' }),
            ev('gen', '$ai_generation', 1500, 1, {
                $ai_generation_id: 'g1',
                $ai_parent_id: 's1',
                $ai_is_error: true,
            }),
        ])
        expect(bars).toEqual([
            expect.objectContaining({
                id: 'root',
                startMs: 0,
                durationMs: 3000,
                lane: 0,
                kind: 'trace',
                parentEventId: null,
            }),
            expect.objectContaining({
                id: 'agent',
                startMs: 300,
                durationMs: 2500,
                lane: 1,
                kind: 'span',
                parentEventId: 'root',
            }),
            expect.objectContaining({
                id: 'gen',
                startMs: 500,
                durationMs: 1000,
                lane: 2,
                kind: 'generation',
                isError: true,
                parentEventId: 'agent',
            }),
        ])
        expect(totalMs).toBe(3000)
        expect(laneCount).toBe(3)
    })

    it('keeps OTel-ingested events (createdAt = span start) at their timestamp', () => {
        // Same trace as above but stamped at span starts, as the OTel pipeline does —
        // $ai_ingestion_source marks them, so bars must not be shifted by their latency.
        const otel = { $ai_ingestion_source: 'otel' }
        const { bars, totalMs } = buildTraceTimeline([
            ev('root', '$ai_trace', 0, 3, { $ai_span_id: 't1', ...otel }),
            ev('agent', '$ai_span', 300, 2.5, { $ai_span_id: 's1', $ai_parent_id: 't1', ...otel }),
            ev('gen', '$ai_generation', 500, 1, { $ai_generation_id: 'g1', $ai_parent_id: 's1', ...otel }),
        ])
        expect(bars).toEqual([
            expect.objectContaining({ id: 'root', startMs: 0, durationMs: 3000, lane: 0 }),
            expect.objectContaining({ id: 'agent', startMs: 300, durationMs: 2500, lane: 1 }),
            expect.objectContaining({ id: 'gen', startMs: 500, durationMs: 1000, lane: 2 }),
        ])
        expect(totalMs).toBe(3000)
    })

    it('spills overlapping siblings into extra sub-lanes and reuses freed ones', () => {
        const { bars, laneCount } = buildTraceTimeline([
            ev('root', '$ai_trace', 3000, 3, { $ai_span_id: 't1' }),
            // g2 [100, 1600] and g1 [200, 1500] overlap in time; g3 [2000, 2900] doesn't.
            ev('g2', '$ai_generation', 1600, 1.5, { $ai_generation_id: 'g2', $ai_parent_id: 't1' }),
            ev('g1', '$ai_generation', 1500, 1.3, { $ai_generation_id: 'g1', $ai_parent_id: 't1' }),
            ev('g3', '$ai_generation', 2900, 0.9, { $ai_generation_id: 'g3', $ai_parent_id: 't1' }),
        ])
        const byId = Object.fromEntries(bars.map((b) => [b.id, b]))
        expect(byId['root'].lane).toBe(0)
        expect(byId['g2'].lane).not.toBe(byId['g1'].lane)
        expect(byId['g3'].lane).toBe(byId['g2'].lane) // g2's lane is free again by 2000ms
        expect(laneCount).toBe(3)
    })

    it('keeps children directly beneath their parent when an overlapping sibling spills over', () => {
        // Two concurrent top-level spans (title [1000,5000] and memory [1000,1800]) plus a
        // later span (root [6000,9000]) with a generation inside. Depth-banded layouts wedge
        // memory's overflow lane between root and its child; flame packing must not.
        const { bars, laneCount } = buildTraceTimeline([
            ev('title', '$ai_span', 5000, 4, { $ai_span_id: 'title' }),
            ev('title-gen', '$ai_generation', 4900, 3.8, { $ai_generation_id: 'tg', $ai_parent_id: 'title' }),
            ev('memory', '$ai_span', 1800, 0.8, { $ai_span_id: 'memory' }),
            ev('root', '$ai_span', 9000, 3, { $ai_span_id: 'root' }),
            ev('root-gen', '$ai_generation', 8900, 2.8, { $ai_generation_id: 'rg', $ai_parent_id: 'root' }),
        ])
        const byId = Object.fromEntries(bars.map((b) => [b.id, b]))
        expect(byId['root-gen'].lane).toBe(byId['root'].lane + 1) // child hugs its parent
        expect(byId['title-gen'].lane).toBe(byId['title'].lane + 1)
        expect(byId['memory'].lane).toBe(2) // pushed below title's whole subtree
        expect(byId['root'].lane).toBe(0)
        expect(laneCount).toBe(3)
    })

    it.each([
        ['$ai_generation', 'generation'],
        ['$ai_embedding', 'embedding'],
        ['$ai_trace', 'trace'],
        ['$ai_span', 'span'],
        ['$ai_tool_call', 'span'], // any unrecognized $ai_* event renders as a span, like the tree
    ])('maps %s to kind %s', (event, kind) => {
        const { bars } = buildTraceTimeline([ev('a', event, 1000, 1)])
        expect(bars[0].kind).toBe(kind)
    })

    it('drops annotation events and renders latency-less events as instant markers', () => {
        const { bars, totalMs } = buildTraceTimeline([
            ev('gen', '$ai_generation', 1000, 1),
            ev('mark', '$ai_span', 500), // no $ai_latency → instant
            ev('feedback', '$ai_feedback', 1200),
            ev('metric', '$ai_metric', 1300),
        ])
        expect(bars.map((b) => b.id).sort()).toEqual(['gen', 'mark'])
        expect(bars.find((b) => b.id === 'mark')).toMatchObject({ startMs: 500, durationMs: 0 })
        expect(totalMs).toBe(1000)
    })

    it('ignores non-string span names and models when labeling', () => {
        // Sender-controlled properties can be malformed objects; rendering one
        // as a React child crashes the scene.
        const { bars } = buildTraceTimeline([
            ev('a', '$ai_generation', 1000, 1, { $ai_span_name: { nested: true }, $ai_model: 'gpt-4.1' }),
        ])
        expect(bars[0].label).toBe('gpt-4.1')
    })

    it('returns empty for no events', () => {
        expect(buildTraceTimeline([])).toEqual({ bars: [], totalMs: 0, laneCount: 0 })
    })

    it.each([
        [250_000, [0, 60_000, 120_000, 180_000, 240_000]], // a ~4m trace ticks whole minutes, not 50s steps
        [47_800, [0, 10_000, 20_000, 30_000, 40_000]],
        [90_000, [0, 15_000, 30_000, 45_000, 60_000, 75_000, 90_000]],
    ])('axis ticks for %ims land on clock-friendly steps', (totalMs, expected) => {
        expect(buildTicks(totalMs)).toEqual(expected)
    })

    it.each([
        [1500, '1.5s'],
        [119_600, '2m'], // rounds up whole — never "1m 60s"
        [250_000, '4m 10s'],
        [5_400_000, '1h 30m'],
    ])('formats %ims as %s', (ms, expected) => {
        expect(formatDuration(ms)).toBe(expected)
    })
})
