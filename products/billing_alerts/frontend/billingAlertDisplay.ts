import type {
    BillingAlertConfigurationApi,
    BillingAlertEventApi,
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

export interface BillingAlertThresholdView {
    /** Numeric threshold under the current configuration, or null when unparsable. */
    thresholdValue: number | null
    thresholdLabel: string
    valueLabel: string
    pickEventValue: (event: BillingAlertEventApi) => number | null
    format: (value: number) => string
}

/** Single home for threshold-type dispatch: which event field to plot, how to label and format it. */
export function thresholdView(alert: BillingAlertConfigurationApi): BillingAlertThresholdView {
    const isRelative = alert.threshold_type === 'relative_increase'
    const rawThreshold = Number(isRelative ? alert.threshold_percentage : alert.threshold_value)
    return {
        thresholdValue: Number.isFinite(rawThreshold) ? rawThreshold : null,
        thresholdLabel: isRelative
            ? `${rawThreshold}% increase`
            : formatBillingValue(rawThreshold, alert.metric, alert.currency),
        valueLabel: isRelative
            ? 'Increase'
            : alert.threshold_type === 'absolute_increase'
              ? 'Increase over baseline'
              : 'Spend',
        pickEventValue: (event: BillingAlertEventApi): number | null => {
            const value = isRelative
                ? event.relative_delta_percentage
                : alert.threshold_type === 'absolute_increase'
                  ? event.absolute_delta
                  : event.current_value
            if (value === null || value === undefined) {
                return null
            }
            const parsed = Number(value)
            return Number.isFinite(parsed) ? parsed : null
        },
        format: (value: number): string =>
            isRelative
                ? `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`
                : formatBillingValue(value, alert.metric, alert.currency),
    }
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
