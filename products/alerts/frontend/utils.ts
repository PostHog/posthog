import type { AlertCheckDelivery } from './types'

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

const DELIVERY_TEMPLATE_LABELS: Record<string, string> = {
    slack: 'Slack',
    discord: 'Discord',
    webhook: 'Webhook',
    teams: 'Microsoft Teams',
}

export function describeDelivery(delivery: AlertCheckDelivery): string {
    if (delivery.channel === 'email') {
        return `Email: ${delivery.target}`
    }
    if (delivery.channel === 'hog_function') {
        const label = (delivery.template && DELIVERY_TEMPLATE_LABELS[delivery.template]) || 'Destination'
        return `${label}: ${delivery.target}`
    }
    return `${delivery.channel}: ${delivery.target}`
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
        return { kind: 'delivered', label: `Yes · ${accepted.length}`, lines: accepted.map(describeDelivery) }
    }
    if (all.length > 0 || targetsNotified) {
        return { kind: 'legacy', label: 'Yes', lines: all.map(describeDelivery) }
    }
    return { kind: 'none' }
}
