import type {
    BillingAlertConfigurationApi,
    BillingAlertMetricEnumApi,
    NotificationDestinationTypeEnumApi,
} from './generated/api.schemas'

export function metricLabel(_metric: BillingAlertMetricEnumApi | undefined): string {
    return 'Spend'
}

export function formatBillingValue(
    value: string | number | null | undefined,
    metric: BillingAlertMetricEnumApi | undefined,
    currency = 'USD'
): string {
    if (value === null || value === undefined) {
        return '–'
    }
    const number = Number(value)
    if (!Number.isFinite(number)) {
        return String(value)
    }
    if (metric === 'spend') {
        return new Intl.NumberFormat(undefined, {
            style: 'currency',
            currency,
            maximumFractionDigits: 2,
        }).format(number)
    }
    return number.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

export function thresholdDescription(alert: BillingAlertConfigurationApi): string {
    if (alert.threshold_type === 'relative_increase') {
        return `${alert.threshold_percentage ?? 0}% over the ${alert.baseline_window_days ?? 7}-day baseline`
    }
    const value = formatBillingValue(alert.threshold_value, alert.metric, alert.currency)
    return alert.threshold_type === 'absolute_increase' ? `${value} above baseline` : `Above ${value}`
}

export function stateLabel(alert: BillingAlertConfigurationApi): string {
    if (alert.state === 'broken') {
        return 'Auto-disabled'
    }
    if (!alert.enabled) {
        return 'Paused'
    }
    return alert.state.replaceAll('_', ' ')
}

export function stateTagType(alert: BillingAlertConfigurationApi): 'success' | 'danger' | 'warning' | 'muted' {
    if (alert.state === 'broken' || alert.state === 'firing') {
        return 'danger'
    }
    if (!alert.enabled) {
        return 'muted'
    }
    if (alert.state === 'errored' || alert.state === 'snoozed') {
        return 'warning'
    }
    return 'success'
}

export function destinationLabel(type: NotificationDestinationTypeEnumApi): string {
    if (type === 'slack') {
        return 'Slack'
    }
    if (type === 'teams') {
        return 'Microsoft Teams'
    }
    return 'Webhook'
}
