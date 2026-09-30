import { LLMTrace } from '~/queries/schema/schema-general'

import { buildTraceTimeline } from '../../../components/TraceTimeline/buildTraceTimeline'
import { TimelineRowData, TraceTreeNode } from '../types'
import { hasTraceError, isErrorEvent, preOrderIds } from './toTraceTree'

export function toTimeline(trace: LLMTrace, tree: TraceTreeNode[]): { rows: TimelineRowData[]; totalMs: number } {
    const { bars, totalMs } = buildTraceTimeline(trace.events)
    const eventsById = new Map(trace.events.map((event) => [event.id, event]))
    const hasError = (id: string): boolean => {
        if (id === trace.id) {
            return hasTraceError(trace)
        }
        const event = eventsById.get(id)
        return event ? isErrorEvent(event) : false
    }
    const treeIndex = new Map(preOrderIds(tree).map((id, index) => [id, index]))
    const position = (id: string): number => treeIndex.get(id) ?? Number.MAX_SAFE_INTEGER
    const ordered = [...bars].sort((a, b) => position(a.id) - position(b.id))
    const depthById = new Map<string, number>()
    const rows = ordered.map((bar) => {
        const depth = bar.parentEventId !== null ? (depthById.get(bar.parentEventId) ?? 0) + 1 : 0
        depthById.set(bar.id, depth)
        return {
            id: bar.id,
            kind: bar.kind,
            name: bar.label,
            depth,
            startMs: bar.startMs,
            durationMs: bar.durationMs > 0 ? bar.durationMs : null,
            hasError: hasError(bar.id),
        }
    })
    return { rows, totalMs }
}
