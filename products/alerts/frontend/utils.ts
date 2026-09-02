import { dayjs } from 'lib/dayjs'

import { AlertState } from '~/queries/schema/schema-general'

import type { AlertCheck, AlertCheckDelivery } from './types'

export enum AlertsTab {
    INSIGHTS = 'insights',
    LOGS = 'logs',
}

export function resolveSnoozeUntil(value: string): string {
    const relativeValue = value.match(/^\+(\d+)([mhdwMy])$/)
    if (!relativeValue) {
        return dayjs(value).toISOString()
    }

    const amount = Number(relativeValue[1])
    const unit = relativeValue[2]
    if (unit === 'm') {
        return dayjs().add(amount, 'minute').toISOString()
    }
    if (unit === 'h') {
        return dayjs().add(amount, 'hour').toISOString()
    }
    if (unit === 'd') {
        return dayjs().add(amount, 'day').toISOString()
    }
    if (unit === 'w') {
        return dayjs().add(amount, 'week').toISOString()
    }
    if (unit === 'M') {
        return dayjs().add(amount, 'month').toISOString()
    }
    return dayjs().add(amount, 'year').toISOString()
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
    | { kind: 'notified' }
    | { kind: 'none' }

export function summarizeDeliveries(
    deliveries: AlertCheckDelivery[] | null,
    targetsNotified: boolean
): DeliverySummary {
    const accepted = (deliveries ?? []).filter((delivery) => delivery.status === 'accepted')
    if (accepted.length > 0) {
        return { kind: 'delivered', label: `Yes · ${accepted.length}`, lines: accepted.map((d) => d.display_label) }
    }
    // Checks predating delivery receipts know only that something was notified, not what.
    return targetsNotified ? { kind: 'notified' } : { kind: 'none' }
}

/** Whether an empty receipt list means a dispatch accepted nothing, rather than one never running. */
export function isFailedDelivery(check: AlertCheck): boolean {
    if (check.state !== AlertState.FIRING || check.notification_suppressed_by_agent) {
        return false
    }
    // Gated on an investigation: no dispatch has run yet, so there is nothing to blame.
    return check.investigation_status !== 'pending' && check.investigation_status !== 'running'
}
