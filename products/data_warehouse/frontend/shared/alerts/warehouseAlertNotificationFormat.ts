import {
    ALERT_PAGERDUTY_REGION_OPTIONS,
    ALERT_PAGERDUTY_SEVERITY_OPTIONS,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import {
    WarehouseAlertCreateDestinationApi,
    WarehouseAlertDestinationApi,
    WarehouseAlertDestinationTypeEnumApi,
} from 'products/warehouse_sources/frontend/generated/api.schemas'

export const PAGERDUTY_ROUTING_KEY_PATTERN = /^[A-Za-z0-9]{32}$/

export const NOTIFICATION_TYPE_OPTIONS: { label: string; value: WarehouseAlertDestinationTypeEnumApi }[] = [
    { label: 'Slack', value: WarehouseAlertDestinationTypeEnumApi.Slack },
    { label: 'Microsoft Teams', value: WarehouseAlertDestinationTypeEnumApi.Teams },
    { label: 'Discord', value: WarehouseAlertDestinationTypeEnumApi.Discord },
    { label: 'PagerDuty', value: WarehouseAlertDestinationTypeEnumApi.Pagerduty },
    { label: 'Webhook', value: WarehouseAlertDestinationTypeEnumApi.Webhook },
]

const TYPE_LABELS = Object.fromEntries(NOTIFICATION_TYPE_OPTIONS.map(({ label, value }) => [value, label])) as Record<
    WarehouseAlertDestinationTypeEnumApi,
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
        case WarehouseAlertDestinationTypeEnumApi.Slack:
            return { title, detail: `#${destination.slack_channel_name || destination.slack_channel_id || 'channel'}` }
        case WarehouseAlertDestinationTypeEnumApi.Pagerduty: {
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
            return { title, detail: destination.webhook_url }
    }
}
