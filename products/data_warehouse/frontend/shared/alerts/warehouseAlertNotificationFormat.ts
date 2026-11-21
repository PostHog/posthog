import {
    ALERT_PAGERDUTY_REGION_OPTIONS,
    ALERT_PAGERDUTY_SEVERITY_OPTIONS,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import {
    WarehouseAlertCreateDestinationApi,
    WarehouseAlertDestinationApi,
    AlertDestinationTypeEnumApi,
} from 'products/warehouse_sources/frontend/generated/api.schemas'

export const PAGERDUTY_ROUTING_KEY_PATTERN = /^[A-Za-z0-9]{32}$/

export const NOTIFICATION_TYPE_OPTIONS: { label: string; value: AlertDestinationTypeEnumApi }[] = [
    { label: 'Slack', value: AlertDestinationTypeEnumApi.Slack },
    { label: 'Microsoft Teams', value: AlertDestinationTypeEnumApi.Teams },
    { label: 'Discord', value: AlertDestinationTypeEnumApi.Discord },
    { label: 'PagerDuty', value: AlertDestinationTypeEnumApi.Pagerduty },
    { label: 'Webhook', value: AlertDestinationTypeEnumApi.Webhook },
]

const TYPE_LABELS = Object.fromEntries(NOTIFICATION_TYPE_OPTIONS.map(({ label, value }) => [value, label])) as Record<
    AlertDestinationTypeEnumApi,
    string
>

/**
 * How a destination reads in the list. A saved destination comes back redacted, with the webhook
 * reduced to its host and the PagerDuty key to its last four characters, so both shapes read the same.
 */
export function describeNotification(destination: WarehouseAlertCreateDestinationApi | WarehouseAlertDestinationApi): {
    title: string
    detail?: string
} {
    const title = TYPE_LABELS[destination.type] ?? destination.type
    switch (destination.type) {
        case AlertDestinationTypeEnumApi.Slack:
            return { title, detail: `#${destination.slack_channel_name || destination.slack_channel_id || 'channel'}` }
        case AlertDestinationTypeEnumApi.Pagerduty: {
            const severity = ALERT_PAGERDUTY_SEVERITY_OPTIONS.find(
                (option) => option.value === destination.pagerduty_severity
            )
            const region = ALERT_PAGERDUTY_REGION_OPTIONS.find(
                (option) => option.value === destination.pagerduty_region
            )
            const parts = [
                `••••${(destination.pagerduty_routing_key ?? '').slice(-4)}`,
                severity?.label,
                region?.label,
            ].filter(Boolean)
            return { title, detail: parts.join(' · ') }
        }
        default:
            return { title, detail: webhookHost(destination.webhook_url) }
    }
}

function webhookHost(url: string | null | undefined): string | undefined {
    if (!url) {
        return undefined
    }
    try {
        return new URL(url).host
    } catch {
        // Without a scheme the URL does not parse, and the raw text can hold the webhook secret.
        return undefined
    }
}
