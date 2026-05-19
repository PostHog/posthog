/** UI labels for Cymbal / `emit_signal` error tracking signal types (`source_type`). */

export const ERROR_TRACKING_SOURCE_TYPE_LABELS: Record<string, string> = {
    issue_created: 'New issue',
    issue_reopened: 'Issue reopened',
    issue_spiking: 'Volume spike',
}

export function errorTrackingTypeLabel(sourceType: string): string {
    return ERROR_TRACKING_SOURCE_TYPE_LABELS[sourceType] ?? sourceType.replace(/_/g, ' ')
}

export function errorTrackingSignalHeaderLine(sourceType: string): string {
    return `Error tracking · ${errorTrackingTypeLabel(sourceType)}`
}
