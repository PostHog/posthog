export interface TraceListRow {
    traceId: string
    timestamp: string | null
    stepId: string | null
    /** One line on why the row is in the list, which the drawer shows above the trace. */
    label?: string
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
