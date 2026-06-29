import { LLMTraceEvent } from '~/queries/schema/schema-general'

export type TraceBarKind = 'generation' | 'span' | 'embedding' | 'other'

export interface TraceTimelineBar {
    id: string
    label: string
    startMs: number
    durationMs: number
    kind: TraceBarKind
    isError: boolean
    // Row index: overlapping/nested events stack into separate lanes so their
    // bars and labels never collide on a shared row.
    lane: number
    // Horizontal room (ms) before the next bar in the same lane begins — or the
    // trace end for the last bar in a lane. The caption below the bar truncates
    // to this so it never overruns its neighbor's label.
    labelRoomMs: number
}

export interface TraceTimelineData {
    bars: TraceTimelineBar[]
    totalMs: number
    laneCount: number
}

function kindOf(event: string): TraceBarKind {
    if (event.includes('generation')) {
        return 'generation'
    }
    if (event.includes('embedding')) {
        return 'embedding'
    }
    if (event.includes('span')) {
        return 'span'
    }
    return 'other'
}

function labelOf(event: LLMTraceEvent): string {
    const p = event.properties || {}
    return p.$ai_span_name || p.$ai_model || event.event || event.id
}

export function buildTraceTimeline(events: LLMTraceEvent[]): TraceTimelineData {
    if (!events.length) {
        return { bars: [], totalMs: 0, laneCount: 0 }
    }

    const times = events.map((e) => new Date(e.createdAt).getTime())
    const traceStart = Math.min(...times)
    const hasSpread = Math.max(...times) - traceStart > 0

    let cursor = 0
    const bars: TraceTimelineBar[] = events.map((event, i) => {
        const durationMs = Math.round((event.properties?.$ai_latency ?? 0) * 1000)
        // With real timestamp spread, position by wall-clock; otherwise lay out
        // sequentially so a poorly-instrumented trace still reads as a waterfall.
        const startMs = hasSpread ? times[i] - traceStart : cursor
        cursor = startMs + durationMs
        return {
            id: event.id,
            label: labelOf(event),
            startMs,
            durationMs,
            kind: kindOf(event.event),
            isError: !!event.properties?.$ai_is_error,
            lane: 0,
            labelRoomMs: 0,
        }
    })

    // Greedy lane packing: each bar drops into the first lane whose previous bar has
    // ended, so non-overlapping bars share a lane and nested spans don't collide.
    const laneEnds: number[] = []
    for (const i of [...bars.keys()].sort((a, b) => bars[a].startMs - bars[b].startMs)) {
        const bar = bars[i]
        let lane = laneEnds.findIndex((end) => end <= bar.startMs)
        if (lane === -1) {
            lane = laneEnds.length
        }
        laneEnds[lane] = bar.startMs + bar.durationMs
        bar.lane = lane
    }

    const totalMs = Math.max(...bars.map((b) => b.startMs + b.durationMs), 0)

    // A bar's caption can run until the next bar in its lane starts (or the trace
    // end for the last bar in a lane), so labels never collide with a neighbor.
    const byLane = new Map<number, TraceTimelineBar[]>()
    for (const bar of bars) {
        const group = byLane.get(bar.lane)
        if (group) {
            group.push(bar)
        } else {
            byLane.set(bar.lane, [bar])
        }
    }
    for (const group of byLane.values()) {
        group.sort((a, b) => a.startMs - b.startMs)
        group.forEach((bar, i) => {
            const next = group[i + 1]
            bar.labelRoomMs = (next ? next.startMs : totalMs) - bar.startMs
        })
    }

    return { bars, totalMs, laneCount: Math.max(laneEnds.length, 1) }
}
