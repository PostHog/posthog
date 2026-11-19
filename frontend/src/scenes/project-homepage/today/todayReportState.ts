/** A report's state on Today: open, or closed by a verdict or on the server. */
export type TodayReportState = 'open' | 'done' | 'dismissed'

const STATE_LABELS: Record<TodayReportState, string | null> = {
    open: null,
    done: 'Resolved',
    dismissed: 'Dismissed',
}

const REPORT_STATUS_STATES: Record<string, TodayReportState> = {
    resolved: 'done',
    suppressed: 'dismissed',
    deleted: 'dismissed',
}

/** What happened to the report, or null while it is still open. */
export function reportStateLabel(state: TodayReportState): string | null {
    return STATE_LABELS[state]
}

export function reportState(status: string): TodayReportState {
    return REPORT_STATUS_STATES[status] ?? 'open'
}
