import {
    ALERT_PAGERDUTY_REGION_OPTIONS,
    ALERT_PAGERDUTY_SEVERITY_OPTIONS,
    AlertNotificationUrlInput,
    AlertPagerDutyRegion,
    AlertPagerDutySeverity,
    pagerDutyPendingDetail,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import {
    PlatformAlertCreateDestinationApi,
    PlatformAlertDestinationApi,
    PlatformAlertDestinationTypeEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

export const DESTINATION_TYPE_OPTIONS: { label: string; value: PlatformAlertDestinationTypeEnumApi }[] = [
    { label: 'Slack', value: PlatformAlertDestinationTypeEnumApi.Slack },
    { label: 'Microsoft Teams', value: PlatformAlertDestinationTypeEnumApi.Teams },
    { label: 'Discord', value: PlatformAlertDestinationTypeEnumApi.Discord },
    { label: 'PagerDuty', value: PlatformAlertDestinationTypeEnumApi.Pagerduty },
    { label: 'Webhook', value: PlatformAlertDestinationTypeEnumApi.Webhook },
]

const TYPE_LABELS = Object.fromEntries(DESTINATION_TYPE_OPTIONS.map(({ value, label }) => [value, label])) as Record<
    PlatformAlertDestinationTypeEnumApi,
    string
>

const URL_INPUTS: Partial<Record<PlatformAlertDestinationTypeEnumApi, AlertNotificationUrlInput>> = {
    [PlatformAlertDestinationTypeEnumApi.Teams]: {
        placeholder: 'https://prod-00.westus.logic.azure.com:443/workflows/...',
        helpText: 'Paste the URL from a Teams "Workflows" (Power Automate) or incoming webhook connector.',
    },
    [PlatformAlertDestinationTypeEnumApi.Discord]: {
        placeholder: 'https://discord.com/api/webhooks/...',
        helpText: 'Paste the webhook URL from the Discord channel settings, under Integrations.',
    },
    [PlatformAlertDestinationTypeEnumApi.Webhook]: { placeholder: 'https://example.com/webhook' },
}

export function destinationTypeLabel(type: PlatformAlertDestinationTypeEnumApi): string {
    return TYPE_LABELS[type] ?? type
}

// Mirrors the API's cap, so a new alert's pending destinations never exceed what its create can save.
export const MAX_DESTINATIONS_PER_ALERT = 5

// The URL shapes the API accepts for each provider, so a URL it would refuse is caught before the alert is
// saved rather than failing when its destinations are added afterwards.
const TEAMS_URL_SHAPES: { host: RegExp; path: (path: string) => boolean }[] = [
    {
        host: /^(?:[a-z0-9-]+\.)+logic\.azure\.com$/,
        path: (path) => path.startsWith('/workflows/') && path.includes('/triggers/manual/paths/invoke'),
    },
    {
        host: /^(?:[a-z0-9-]+\.)+webhook\.office\.com$/,
        path: (path) => path.startsWith('/webhookb2/') && path.includes('/IncomingWebhook/'),
    },
    { host: /^(?:[a-z0-9-]+\.)+(?:powerautomate\.com|flow\.microsoft\.com)$/, path: (path) => path !== '/' },
    {
        host: /^(?:[a-z0-9-]+\.)+environment\.api\.powerplatform\.com$/,
        path: (path) => path.startsWith('/powerautomate/automations/direct/') && path.includes('/workflows/'),
    },
]

function parsedHttpsUrl(value: string): URL | null {
    try {
        const url = new URL(value)
        return url.protocol === 'https:' && !url.username && !url.password ? url : null
    } catch {
        return null
    }
}

// Teams and Discord URLs only ever use the default port. A generic webhook may run on any.
function usesDefaultPort(url: URL): boolean {
    return ['', '443'].includes(url.port)
}

export function destinationUrlError(type: PlatformAlertDestinationTypeEnumApi, value: string): string | undefined {
    const trimmed = value.trim()
    if (!trimmed) {
        return 'Enter a webhook URL'
    }
    const url = parsedHttpsUrl(trimmed)
    if (!url) {
        return 'Enter an https URL'
    }
    if (type === PlatformAlertDestinationTypeEnumApi.Discord) {
        return usesDefaultPort(url) && url.hostname === 'discord.com' && url.pathname.startsWith('/api/webhooks/')
            ? undefined
            : 'Enter a Discord webhook URL, starting https://discord.com/api/webhooks/'
    }
    if (type === PlatformAlertDestinationTypeEnumApi.Teams) {
        const host = url.hostname.toLowerCase()
        return usesDefaultPort(url) &&
            TEAMS_URL_SHAPES.some((shape) => shape.host.test(host) && shape.path(url.pathname))
            ? undefined
            : 'Enter the URL from a Teams workflow or incoming webhook'
    }
    return undefined
}

export function urlInputFor(type: PlatformAlertDestinationTypeEnumApi): AlertNotificationUrlInput | undefined {
    return URL_INPUTS[type]
}

function pagerDutyDetail(severity?: string, region?: string): string {
    const severityLabel = ALERT_PAGERDUTY_SEVERITY_OPTIONS.find((option) => option.value === severity)?.label
    const regionLabel = ALERT_PAGERDUTY_REGION_OPTIONS.find((option) => option.value === region)?.label
    return [severityLabel ?? severity, regionLabel ?? region].filter(Boolean).join(' · ')
}

// The path and query of a webhook URL carry its secret, so only the scheme and host are shown, as the API
// does for saved destinations.
export function redactedUrl(url: string | undefined): string | undefined {
    if (!url) {
        return undefined
    }
    try {
        return new URL(url).origin
    } catch {
        return undefined
    }
}

export interface DestinationDescription {
    title: string
    detail?: string
}

export function describeDestination(destination: PlatformAlertDestinationApi): DestinationDescription {
    const title = TYPE_LABELS[destination.type] ?? destination.type
    switch (destination.type) {
        case PlatformAlertDestinationTypeEnumApi.Slack:
            return { title, detail: `#${destination.slack_channel_name || destination.slack_channel_id || 'channel'}` }
        case PlatformAlertDestinationTypeEnumApi.Pagerduty:
            return {
                title,
                // The API returns only the key's last four characters.
                detail: [
                    `••••${destination.pagerduty_routing_key ?? ''}`,
                    pagerDutyDetail(destination.pagerduty_severity, destination.pagerduty_region),
                ].join(' · '),
            }
        default:
            return { title, detail: destination.webhook_url }
    }
}

export function describePendingDestination(destination: PlatformAlertCreateDestinationApi): DestinationDescription {
    const title = TYPE_LABELS[destination.type] ?? destination.type
    switch (destination.type) {
        case PlatformAlertDestinationTypeEnumApi.Slack:
            return { title, detail: `#${destination.slack_channel_name ?? destination.slack_channel_id ?? 'channel'}` }
        case PlatformAlertDestinationTypeEnumApi.Pagerduty:
            return {
                title,
                detail: pagerDutyPendingDetail({
                    routingKey: destination.pagerduty_routing_key ?? '',
                    severity: (destination.pagerduty_severity ?? 'critical') as AlertPagerDutySeverity,
                    region: (destination.pagerduty_region ?? 'us') as AlertPagerDutyRegion,
                }),
            }
        default:
            return { title, detail: redactedUrl(destination.webhook_url) }
    }
}
