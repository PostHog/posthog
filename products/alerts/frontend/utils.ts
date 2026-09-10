import { dayjs, dayjsNowInTimezone } from 'lib/dayjs'
import { getAppContext } from 'lib/utils/getAppContext'

import { AlertState, ForecastConditionType } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { AlertCheck, AlertCheckDelivery, AlertType } from './types'

export enum AlertsTab {
    INSIGHTS = 'insights',
    LOGS = 'logs',
}

export function hasEffectiveResourceAccess(resourceType: AccessControlResourceType): boolean {
    return getAppContext()?.effective_resource_access_control?.[resourceType] !== AccessControlLevel.None
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

/** The server expires a target alert on the project's calendar date, so the label has to read the
 * same clock. A browser in another timezone would otherwise disagree for part of every day. */
export function isTargetDatePassed(alert: AlertType, projectTimezone: string): boolean {
    const config = alert.forecast_config
    if (config?.condition !== ForecastConditionType.TARGET_BY_DATE || !config.target_date) {
        return false
    }
    const targetDate = dayjs(config.target_date)
    // A stored date can be in an ISO form dayjs cannot read. With no date to compare, the tag would
    // announce an expiry that may not have happened.
    if (!targetDate.isValid()) {
        return false
    }
    return !alert.enabled && !targetDate.isAfter(dayjsNowInTimezone(projectTimezone), 'day')
}
