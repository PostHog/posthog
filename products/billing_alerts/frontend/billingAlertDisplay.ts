import type { AlertingWizardStep } from 'lib/components/Alerting'

import type {
    BillingAlertConfigurationStateEnumApi,
    MetricEnumApi,
} from 'products/billing_alerts/frontend/generated/api.schemas'

import { BILLING_ALERT_NUMBER_FIELDS } from './billingAlertFields'
import { BillingAlertWizardStep } from './billingAlertsLogic'
import type { BillingAlertConfiguration, BillingAlertDestinationKey } from './billingAlertsLogic'

export const BILLING_ALERT_WIZARD_STEPS: AlertingWizardStep<BillingAlertWizardStep>[] = [
    { key: BillingAlertWizardStep.Destination, label: 'Destination' },
    { key: BillingAlertWizardStep.Trigger, label: 'Trigger' },
    { key: BillingAlertWizardStep.Configure, label: 'Configure' },
]

export const BILLING_ALERT_DESTINATIONS: {
    key: BillingAlertDestinationKey
    name: string
    description: string
    icon: string
}[] = [
    {
        key: 'slack',
        name: 'Slack',
        description: 'Post to a Slack channel when the billing alert fires, resolves, or errors.',
        icon: '/static/services/slack.png',
    },
    {
        key: 'teams',
        name: 'Microsoft Teams',
        description: 'Post to a Microsoft Teams webhook when the billing alert fires, resolves, or errors.',
        icon: '/static/services/microsoft-teams.png',
    },
    {
        key: 'webhook',
        name: 'Webhook',
        description: 'Send an HTTP request when the billing alert fires, resolves, or errors.',
        icon: '/static/services/webhook.svg',
    },
]

export { BILLING_ALERT_NUMBER_FIELDS }

export function metricLabel(metric: MetricEnumApi | undefined): string {
    return metric === 'usage' ? 'Usage' : 'Spend'
}

export function formatValue(value: string | null | undefined, metric: MetricEnumApi | undefined): string {
    if (value === null || value === undefined) {
        return '-'
    }
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) {
        return value
    }
    if (metric === 'spend') {
        return `$${numeric.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    }
    return numeric.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

export function thresholdDescription(alert: BillingAlertConfiguration): string {
    const thresholdType = alert.threshold_type ?? 'relative_increase'
    if (thresholdType === 'relative_increase') {
        return `${alert.threshold_percentage}% over ${alert.baseline_window_days}d baseline`
    }
    return `${formatValue(alert.threshold_value, alert.metric)} ${thresholdType.replaceAll('_', ' ')}`
}

export function stateTagType(
    state: BillingAlertConfigurationStateEnumApi,
    enabled: boolean | undefined
): 'success' | 'danger' | 'warning' | 'muted' {
    if (!enabled) {
        return 'muted'
    }
    if (state === 'firing' || state === 'broken') {
        return 'danger'
    }
    if (state === 'errored' || state === 'snoozed') {
        return 'warning'
    }
    return 'success'
}

export function stateLabel(state: BillingAlertConfigurationStateEnumApi, enabled: boolean | undefined): string {
    if (!enabled) {
        return 'Paused'
    }
    return state.replaceAll('_', ' ')
}

export function destinationLabel(destinationKey: BillingAlertDestinationKey): string {
    return BILLING_ALERT_DESTINATIONS.find((destination) => destination.key === destinationKey)?.name ?? 'Destination'
}

export function destinationWebhookLabel(destinationKey: BillingAlertDestinationKey): string {
    return destinationKey === 'teams' ? 'Microsoft Teams webhook URL' : 'Webhook URL'
}

export function destinationDisabledReason(destinationKey: BillingAlertDestinationKey): string {
    if (destinationKey === 'slack') {
        return 'Slack connection and channel are required.'
    }
    return `Enter a valid ${destinationWebhookLabel(destinationKey).toLowerCase()}.`
}
