import { slackChannelId, slackChannelName } from 'lib/integrations/slackChannel'

import {
    AlertPagerDutyRegion,
    AlertPagerDutySeverity,
    pagerDutyRoutingKeyError,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'

import type {
    PlatformAlertCreateDestinationApi,
    PlatformAlertDestinationApi,
    PlatformAlertDestinationTypeEnumApi,
} from '../generated/api.schemas'
import { RECEIVER_TYPE_OPTIONS } from '../routing/platformAlertRoutingFormat'

// Routes only send messages, so their receiver types leave PagerDuty out. An alert's own destinations are
// the only place an incident manager can be set up.
export const DESTINATION_TYPE_OPTIONS: { value: PlatformAlertDestinationTypeEnumApi; label: string }[] = [
    ...RECEIVER_TYPE_OPTIONS,
    { value: 'pagerduty', label: 'PagerDuty' },
]

export interface DestinationForm {
    type: PlatformAlertDestinationTypeEnumApi
    // Null picks the project's first Slack workspace.
    slackWorkspaceId: number | null
    // `<channel id>|#<channel name>`, the value `SlackChannelPicker` reads and writes.
    slackChannel: string | null
    webhookUrl: string
    pagerDutyRoutingKey: string
    pagerDutySeverity: AlertPagerDutySeverity
    pagerDutyRegion: AlertPagerDutyRegion
}

// Mirrors the API's cap, so a new alert's pending destinations never exceed what its create can save.
export const MAX_DESTINATIONS_PER_ALERT = 5

export const EMPTY_DESTINATION_FORM: DestinationForm = {
    type: 'slack',
    slackWorkspaceId: null,
    slackChannel: null,
    webhookUrl: '',
    pagerDutyRoutingKey: '',
    pagerDutySeverity: 'critical',
    pagerDutyRegion: 'us',
}

export function validateDestinationForm(form: DestinationForm): Partial<Record<keyof DestinationForm, string>> {
    if (form.type === 'slack') {
        return form.slackChannel ? {} : { slackChannel: 'Pick a channel' }
    }
    if (form.type === 'pagerduty') {
        const keyError = pagerDutyRoutingKeyError(form.pagerDutyRoutingKey)
        return keyError ? { pagerDutyRoutingKey: keyError } : {}
    }
    const url = form.webhookUrl.trim()
    if (!url) {
        return { webhookUrl: 'Enter a URL' }
    }
    return url.startsWith('https://') ? {} : { webhookUrl: 'The URL must start with https://' }
}

export function destinationBody(
    form: DestinationForm,
    slackWorkspaceId: number | undefined
): PlatformAlertCreateDestinationApi {
    if (form.type === 'slack') {
        const channelId = slackChannelId(form.slackChannel ?? '')
        return {
            type: 'slack',
            slack_workspace_id: slackWorkspaceId,
            slack_channel_id: channelId,
            slack_channel_name: slackChannelName(form.slackChannel ?? '') ?? channelId,
        }
    }
    if (form.type === 'pagerduty') {
        return {
            type: 'pagerduty',
            pagerduty_routing_key: form.pagerDutyRoutingKey.trim(),
            pagerduty_severity: form.pagerDutySeverity,
            pagerduty_region: form.pagerDutyRegion,
        }
    }
    return { type: form.type, webhook_url: form.webhookUrl.trim() }
}

const TYPE_LABELS: Record<PlatformAlertDestinationTypeEnumApi, string> = {
    slack: 'Slack',
    teams: 'Microsoft Teams',
    discord: 'Discord',
    webhook: 'Webhook',
    pagerduty: 'PagerDuty',
}

export function destinationTypeLabel(type: PlatformAlertDestinationTypeEnumApi): string {
    return TYPE_LABELS[type] ?? type
}

/** Where a saved or pending destination sends, such as `#alerts` or a webhook's host. */
export function destinationTarget(
    destination: PlatformAlertDestinationApi | PlatformAlertCreateDestinationApi
): string {
    if (destination.type === 'slack') {
        return `#${(destination.slack_channel_name ?? destination.slack_channel_id ?? '').replace(/^#/, '')}`
    }
    if (destination.type === 'pagerduty') {
        // A saved key comes back as its last four characters. A pending one is the whole secret, so show only those.
        const key = destination.pagerduty_routing_key ?? ''
        return key ? `Key ending ${key.slice(-4)}, ${destination.pagerduty_severity ?? 'critical'}` : ''
    }
    return destination.webhook_url ?? ''
}
