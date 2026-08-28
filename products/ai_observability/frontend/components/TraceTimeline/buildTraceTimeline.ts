import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { LLMEventKind, getLLMEventKind, latencyMs, operationStartMs } from '../../utils'

export type TraceBarKind = LLMEventKind

export interface TraceTimelineBar {
    id: string
    label: string
    startMs: number
    // 0 means the event has no latency — rendered as an instant marker.
    durationMs: number
    kind: TraceBarKind
    isError: boolean
    // Flame-chart row: an event's children always render directly below it;
    // concurrent siblings are pushed below each other's whole subtree.
    lane: number
    // event.id of the direct parent's bar, when the parent is drawn — lets the
    // chart draw nesting connectors and tell children from concurrent siblings.
    parentEventId: string | null
}

export interface TraceTimelineData {
    bars: TraceTimelineBar[]
    totalMs: number
    laneCount: number
}

// Annotation events the trace tree hides too — they aren't steps in time.
const HIDDEN_EVENTS = new Set(['$ai_feedback', '$ai_metric'])

// Axis steps land on clock-friendly values (…15s, 30s, 1m, 2m…), not decimal
// multiples — a 4m trace should tick 1m/2m/3m, never 50s/1m 40s.
const TICK_STEPS_MS = [
    1, 2, 5, 10, 20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 15_000, 30_000, 60_000, 120_000, 300_000, 600_000,
    900_000, 1_800_000, 3_600_000, 7_200_000, 10_800_000, 21_600_000, 43_200_000, 86_400_000,
]
const MAX_TICKS = 6

export function buildTicks(totalMs: number): number[] {
    // Non-finite totals would make the tick loop below never terminate.
    if (!isFinite(totalMs) || totalMs < 10) {
        return [0]
    }
    const step =
        TICK_STEPS_MS.find((s) => totalMs / s <= MAX_TICKS) ??
        86_400_000 * Math.ceil(totalMs / (MAX_TICKS * 86_400_000))
    const ticks: number[] = []
    for (let tick = 0; tick <= totalMs; tick += step) {
        ticks.push(tick)
    }
    return ticks
}

// Compact durations: 240ms, 1.5s, 4m 30s, 2h 15m — terse enough to fit inside
// bars and axis labels.
export function formatDuration(ms: number): string {
    if (ms <= 0) {
        return '0'
    }
    if (ms < 1000) {
        return `${Math.round(ms)}ms`
    }
    if (ms < 60_000) {
        return `${parseFloat((ms / 1000).toFixed(2))}s`
    }
    if (ms < 3_600_000) {
        const totalSeconds = Math.round(ms / 1000)
        const minutes = Math.floor(totalSeconds / 60)
        const seconds = totalSeconds % 60
        return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`
    }
    const totalMinutes = Math.round(ms / 60_000)
    const hours = Math.floor(totalMinutes / 60)
    const minutes = totalMinutes % 60
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`
}

// Instant events still occupy a sliver of time when resolving lane collisions.
const OVERLAP_MIN_MS = 1

function labelOf(event: LLMTraceEvent): string {
    const p = event.properties || {}
    // Properties are sender-controlled and can be non-strings; rendering an
    // object as a React child would crash the scene.
    const name = typeof p.$ai_span_name === 'string' ? p.$ai_span_name : undefined
    const model = typeof p.$ai_model === 'string' ? p.$ai_model : undefined
    return name || model || event.event || event.id
}

interface TimedEvent {
    idx: number
    event: LLMTraceEvent
    /** The operation's start as epoch ms, see the timestamp-convention note below. */
    startAt: number
    latencyMs: number
    /** Same node identity conventions as restoreTree, so nesting matches the tree. */
    nodeId: string
    parentId: string | null
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
        const p = event.properties || {}
        timed.push({
            idx: timed.length,
            event,
            startAt: operationStartMs(event),
            latencyMs: latencyMs(event),
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

    const bars: TraceTimelineBar[] = timed.map((timedEvent) => ({
        id: timedEvent.event.id,
        label: labelOf(timedEvent.event),
        startMs: timedEvent.startAt - traceStart,
        durationMs: timedEvent.latencyMs,
        kind: getLLMEventKind(timedEvent.event),
        isError: !!timedEvent.event.properties?.$ai_is_error,
        lane: 0,
        parentEventId: null,
    }))

    const totalMs = Math.max(...bars.map((b) => b.startMs + b.durationMs))

    // Restore the forest with the tree's parent-resolution rules: an event whose
    // parent isn't among the events (e.g. the $ai_trace root the query runner
    // strips out) starts its own top-level subtree.
    const childrenOf = new Map<string, TimedEvent[]>()
    const roots: TimedEvent[] = []
    for (const timedEvent of timed) {
        const parent = timedEvent.parentId != null ? byNodeId.get(timedEvent.parentId) : undefined
        if (!parent || parent === timedEvent) {
            roots.push(timedEvent)
            continue
        }
        bars[timedEvent.idx].parentEventId = parent.event.id
        const siblings = childrenOf.get(parent.nodeId)
        if (siblings) {
            siblings.push(timedEvent)
        } else {
            childrenOf.set(parent.nodeId, [timedEvent])
        }
    }

    const startOf = (e: TimedEvent): number => e.startAt
    const endOf = (e: TimedEvent): number => e.startAt + Math.max(e.latencyMs, OVERLAP_MIN_MS)

    // Each sibling subtree is a rectangle: its time interval × its height in lanes.
    // Siblings pack greedily; one that overlaps another in time drops below that
    // sibling's whole rectangle, so a bar's children are always directly beneath it.
    const offs: number[] = []
    const visited = new Set<number>()

    function packBand(siblings: TimedEvent[]): number {
        const ordered = [...siblings].sort(
            (a, b) => startOf(a) - startOf(b) || endOf(b) - startOf(b) - (endOf(a) - startOf(a))
        )
        const placed: { start: number; end: number; off: number; h: number }[] = []
        let bandHeight = 0
        for (const sibling of ordered) {
            if (visited.has(sibling.idx)) {
                continue
            }
            visited.add(sibling.idx)
            const kids = childrenOf.get(sibling.nodeId)
            const h = 1 + (kids ? packBand(kids) : 0)
            const start = startOf(sibling)
            const end = endOf(sibling)
            const overlapping = placed.filter((p) => p.end > start && p.start < end)
            let off = 0
            for (const candidate of [0, ...overlapping.map((p) => p.off + p.h)].sort((a, b) => a - b)) {
                if (!overlapping.some((p) => candidate < p.off + p.h && p.off < candidate + h)) {
                    off = candidate
                    break
                }
            }
            offs[sibling.idx] = off
            placed.push({ start, end, off, h })
            bandHeight = Math.max(bandHeight, off + h)
        }
        return bandHeight
    }

    let laneCount = packBand(roots)

    const assignLanes = (timedEvent: TimedEvent, baseLane: number): void => {
        const lane = baseLane + (offs[timedEvent.idx] ?? 0)
        bars[timedEvent.idx].lane = lane
        // Only the canonical event for a node id owns its children, so duplicated
        // span ids don't assign the same subtree twice.
        if (byNodeId.get(timedEvent.nodeId) !== timedEvent) {
            return
        }
        for (const kid of childrenOf.get(timedEvent.nodeId) ?? []) {
            assignLanes(kid, lane + 1)
        }
    }
    for (const root of roots) {
        assignLanes(root, 0)
    }

    // Events stranded by a parent-reference cycle never get reached from a root —
    // lay them out flat at the bottom instead of dropping them.
    const stranded = timed.filter((e) => !visited.has(e.idx))
    if (stranded.length) {
        const laneEnds: number[] = []
        for (const timedEvent of [...stranded].sort((a, b) => startOf(a) - startOf(b))) {
            let subLane = laneEnds.findIndex((end) => end <= startOf(timedEvent))
            if (subLane === -1) {
                subLane = laneEnds.length
            }
            laneEnds[subLane] = endOf(timedEvent)
            bars[timedEvent.idx].lane = laneCount + subLane
        }
        laneCount += laneEnds.length
    }

    bars.sort((a, b) => a.lane - b.lane || a.startMs - b.startMs)
    return { bars, totalMs, laneCount }
}
