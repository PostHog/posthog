import { LLMTraceEvent } from '~/queries/schema/schema-general'

export type TraceBarKind = 'generation' | 'span' | 'embedding' | 'trace'

export interface TraceTimelineBar {
    id: string
    label: string
    startMs: number
    // 0 means the event has no latency — rendered as an instant marker.
    durationMs: number
    kind: TraceBarKind
    isError: boolean
    // Flame-chart row: outer operations sit above the operations they contain.
    lane: number
}

export interface TraceTimelineData {
    bars: TraceTimelineBar[]
    totalMs: number
    laneCount: number
}

// Annotation events the trace tree hides too — they aren't steps in time.
const HIDDEN_EVENTS = new Set(['$ai_feedback', '$ai_metric'])

// Mirrors getEventType in ../../utils.ts so bar colors match the tree's tags.
function kindOf(event: string): TraceBarKind {
    switch (event) {
        case '$ai_generation':
            return 'generation'
        case '$ai_embedding':
            return 'embedding'
        case '$ai_trace':
            return 'trace'
        default:
            return 'span'
    }
}

function labelOf(event: LLMTraceEvent): string {
    const p = event.properties || {}
    return p.$ai_span_name || p.$ai_model || event.event || event.id
}

interface TimedEvent {
    event: LLMTraceEvent
    /** The operation's start as epoch ms, see the timestamp-convention note below. */
    startAt: number
    latencyMs: number
    /** Same node identity conventions as restoreTree, so nesting matches the tree. */
    nodeId: string
    parentId: string | null
}

function depthOf(timedEvent: TimedEvent, byNodeId: Map<string, TimedEvent>): number {
    let depth = 0
    const seen = new Set<string>([timedEvent.nodeId])
    let parent = timedEvent.parentId != null ? byNodeId.get(timedEvent.parentId) : undefined
    while (parent && !seen.has(parent.nodeId)) {
        depth++
        seen.add(parent.nodeId)
        parent = parent.parentId != null ? byNodeId.get(parent.parentId) : undefined
    }
    return depth
}

export function buildTraceTimeline(events: LLMTraceEvent[]): TraceTimelineData {
    const timed: TimedEvent[] = []
    for (const event of events) {
        if (HIDDEN_EVENTS.has(event.event)) {
            continue
        }
        const t = new Date(event.createdAt).getTime()
        if (!isFinite(t)) {
            continue
        }
        const latencySec = Number(event.properties?.$ai_latency)
        const latencyMs = isFinite(latencySec) && latencySec > 0 ? latencySec * 1000 : 0
        const p = event.properties || {}
        timed.push({
            event,
            // PostHog AI SDKs capture an event when the operation finishes, so its
            // timestamp is the END and $ai_latency the duration — while OTel-ingested
            // spans (marked with $ai_ingestion_source) keep the span's START time.
            startAt: p.$ai_ingestion_source === 'otel' ? t : t - latencyMs,
            latencyMs,
            nodeId: p.$ai_generation_id ?? p.$ai_span_id ?? event.id,
            parentId: p.$ai_parent_id ?? p.$ai_trace_id ?? null,
        })
    }
    if (!timed.length) {
        return { bars: [], totalMs: 0, laneCount: 0 }
    }

    const byNodeId = new Map<string, TimedEvent>()
    for (const timedEvent of timed) {
        byNodeId.set(timedEvent.nodeId, timedEvent)
    }

    const traceStart = Math.min(...timed.map((e) => e.startAt))

    const bars: (TraceTimelineBar & { depth: number })[] = timed.map((timedEvent) => ({
        id: timedEvent.event.id,
        label: labelOf(timedEvent.event),
        startMs: timedEvent.startAt - traceStart,
        durationMs: timedEvent.latencyMs,
        kind: kindOf(timedEvent.event.event),
        isError: !!timedEvent.event.properties?.$ai_is_error,
        lane: 0,
        depth: depthOf(timedEvent, byNodeId),
    }))

    const totalMs = Math.max(...bars.map((b) => b.startMs + b.durationMs))

    // Flame layout: one band of lanes per tree depth, so containers render above
    // their contents. Within a depth, overlapping bars (concurrent siblings) spill
    // into extra sub-lanes; non-overlapping ones share a lane.
    const byDepth = new Map<number, (TraceTimelineBar & { depth: number })[]>()
    for (const bar of bars) {
        const group = byDepth.get(bar.depth)
        if (group) {
            group.push(bar)
        } else {
            byDepth.set(bar.depth, [bar])
        }
    }
    let laneCount = 0
    for (const depth of [...byDepth.keys()].sort((a, b) => a - b)) {
        const group = byDepth.get(depth)!
        group.sort((a, b) => a.startMs - b.startMs || b.durationMs - a.durationMs)
        const laneEnds: number[] = []
        for (const bar of group) {
            let subLane = laneEnds.findIndex((end) => end <= bar.startMs)
            if (subLane === -1) {
                subLane = laneEnds.length
            }
            laneEnds[subLane] = bar.startMs + bar.durationMs
            bar.lane = laneCount + subLane
        }
        laneCount += laneEnds.length
    }

    bars.sort((a, b) => a.lane - b.lane || a.startMs - b.startMs)
    return { bars: bars.map(({ depth: _depth, ...bar }) => bar), totalMs, laneCount }
}
