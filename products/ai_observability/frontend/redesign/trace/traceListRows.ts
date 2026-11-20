import type { TracePersonApi } from '../../generated/api.schemas'
import type { TraceOverview } from './types'

export interface TraceListRow {
    traceId: string
    timestamp: string | null
    stepId: string | null
    /** One line on why the row is in the list, which the drawer shows above the trace. */
    label?: string
    overview?: TraceOverview
    /** The step the trace opens on, when the row knows it, so the drawer reads it beside the trace. */
    defaultStepId?: string
    person?: TracePersonApi
}

export function uniqueTraces(rows: TraceListRow[]): TraceListRow[] {
    const firstRowByTrace = new Map<string, TraceListRow>()
    for (const row of rows) {
        if (!firstRowByTrace.has(row.traceId)) {
            firstRowByTrace.set(row.traceId, row)
        }
    }
    return [...firstRowByTrace.values()]
}
