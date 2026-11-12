export interface TraceListRow {
    traceId: string
    timestamp: string | null
    stepId: string | null
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
