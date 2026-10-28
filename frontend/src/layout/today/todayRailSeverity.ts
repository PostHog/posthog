import type { BillingAlertConfig } from 'scenes/billing/billingLogic'

/**
 * How much a rail signal needs attention. `ok` is a healthy reading worth showing in green,
 * `none` is nothing to show, and `notice` is news rather than a problem.
 */
export type TodayRailSeverity = 'none' | 'ok' | 'notice' | 'warning' | 'critical'

export type TodayBadgeStatus = 'success' | 'warning' | 'danger'

const RANK: Record<TodayRailSeverity, number> = { none: 0, ok: 0, notice: 1, warning: 2, critical: 3 }

export const SEVERITY_TEXT_CLASS: Record<TodayRailSeverity, string> = {
    none: 'text-muted-foreground',
    ok: 'text-success-foreground',
    notice: 'text-muted-foreground',
    warning: 'text-warning-foreground',
    critical: 'text-destructive-foreground',
}

export const SEVERITY_INDICATOR: Record<TodayRailSeverity, 'default' | 'warning' | 'destructive' | undefined> = {
    none: undefined,
    ok: undefined,
    notice: 'default',
    warning: 'warning',
    critical: 'destructive',
}

export function worstSeverity(...severities: TodayRailSeverity[]): TodayRailSeverity {
    return severities.reduce((worst, severity) => (RANK[severity] > RANK[worst] ? severity : worst), 'none')
}

export function severityFromBadgeStatus(status: TodayBadgeStatus): TodayRailSeverity {
    return status === 'danger' ? 'critical' : status === 'warning' ? 'warning' : 'ok'
}

export function severityFromBillingAlert(alert: BillingAlertConfig | null): TodayRailSeverity {
    if (!alert) {
        return 'none'
    }
    if (alert.status === 'error') {
        return 'critical'
    }
    // The banner shows an approaching usage limit as info, but only acting before the cap prevents dropped data.
    if (alert.status === 'warning' || alert.kind === 'usage_limit') {
        return 'warning'
    }
    return 'none'
}
