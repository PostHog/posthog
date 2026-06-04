export const ERROR_TRACKING_WIDGET_ORDER_BY_OPTIONS = [
    { value: 'occurrences', label: 'Occurrences' },
    { value: 'last_seen', label: 'Last seen' },
    { value: 'first_seen', label: 'First seen' },
    { value: 'users', label: 'Users' },
    { value: 'sessions', label: 'Sessions' },
] as const

/** True when the project can query error tracking issues (matches tile setup prompt gating). */
export function canConfigureErrorTrackingWidgetIssues(
    team: { autocapture_exceptions_opt_in?: boolean | null } | null | undefined,
    hasSentExceptionEvent: boolean | undefined
): boolean {
    if (!team) {
        return false
    }

    return hasSentExceptionEvent === true || !!team.autocapture_exceptions_opt_in
}
