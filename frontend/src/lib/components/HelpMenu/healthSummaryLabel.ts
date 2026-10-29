export function healthSummaryLabel(unsnoozedCount: number, snoozedCount: number): string {
    if (unsnoozedCount > 0) {
        return `${unsnoozedCount} health issue${unsnoozedCount === 1 ? '' : 's'}`
    }
    if (snoozedCount > 0) {
        return `${snoozedCount} snoozed health issue${snoozedCount === 1 ? '' : 's'}`
    }
    return 'All systems healthy'
}
