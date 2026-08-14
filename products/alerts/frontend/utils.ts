import { AlertState } from '~/queries/schema/schema-general'

import type { AlertCheck, AlertCheckDelivery } from './types'

export enum AlertsTab {
    INSIGHTS = 'insights',
    LOGS = 'logs',
}

interface AlertsAccessState {
    alertId: string | null
    requestedTab: string | undefined
    canViewInsightAlerts: boolean
    canViewLogAlerts: boolean
}

interface AlertsTabsState {
    canViewInsightAlerts: boolean
    canViewLogAlerts: boolean
}

export function getActiveAlertsTab({
    alertId,
    requestedTab,
    canViewInsightAlerts,
    canViewLogAlerts,
}: AlertsAccessState): AlertsTab | null {
    if (alertId !== null) {
        return canViewInsightAlerts ? AlertsTab.INSIGHTS : null
    }
    if (requestedTab === AlertsTab.LOGS && canViewLogAlerts) {
        return AlertsTab.LOGS
    }
    if (canViewInsightAlerts) {
        return AlertsTab.INSIGHTS
    }
    if (canViewLogAlerts) {
        return AlertsTab.LOGS
    }
    return null
}

export function getAlertsTabs({
    canViewInsightAlerts,
    canViewLogAlerts,
}: AlertsTabsState): { key: AlertsTab; label: string }[] {
    const tabs: { key: AlertsTab; label: string }[] = []
    if (canViewInsightAlerts) {
        tabs.push({ key: AlertsTab.INSIGHTS, label: 'Insight alerts' })
    }
    if (canViewLogAlerts) {
        tabs.push({ key: AlertsTab.LOGS, label: 'Log alerts' })
    }
    return tabs
}

export type DeliverySummary =
    | { kind: 'delivered'; label: string; lines: string[] }
    | { kind: 'legacy'; label: string; lines: string[] }
    | { kind: 'none' }

export function summarizeDeliveries(
    deliveries: AlertCheckDelivery[] | null | undefined,
    targetsNotified: boolean
): DeliverySummary {
    const all = deliveries ?? []
    const accepted = all.filter((delivery) => delivery.status === 'accepted')
    if (accepted.length > 0) {
        return { kind: 'delivered', label: `Yes · ${accepted.length}`, lines: accepted.map((d) => d.display_label) }
    }
    if (all.length > 0 || targetsNotified) {
        return { kind: 'legacy', label: 'Yes', lines: all.map((d) => d.display_label) }
    }
    return { kind: 'none' }
}

/** Whether an empty receipt list means a dispatch accepted nothing, rather than one never running. */
export function isFailedDelivery(check: AlertCheck): boolean {
    if (check.state !== AlertState.FIRING || check.notification_suppressed_by_agent) {
        return false
    }
    // Gated on an investigation: no dispatch has run yet, so there is nothing to blame.
    return check.investigation_status !== 'pending' && check.investigation_status !== 'running'
}
