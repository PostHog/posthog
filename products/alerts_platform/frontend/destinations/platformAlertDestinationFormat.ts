import { slackChannelId, slackChannelName } from 'lib/integrations/slackChannel'

import type {
    PlatformAlertCreateDestinationApi,
    PlatformAlertDestinationApi,
    PlatformAlertDestinationTypeEnumApi,
} from '../generated/api.schemas'
import { RECEIVER_TYPE_OPTIONS } from '../routing/platformAlertRoutingFormat'

/** The destination types an alert's own form offers. PagerDuty needs its incident settings, so it is left to the API for now. */
export type DestinationFormType = Exclude<PlatformAlertDestinationTypeEnumApi, 'pagerduty'>

export const DESTINATION_TYPE_OPTIONS = RECEIVER_TYPE_OPTIONS as { value: DestinationFormType; label: string }[]

export interface DestinationForm {
    type: DestinationFormType
    // Null picks the project's first Slack workspace.
    slackWorkspaceId: number | null
    // `<channel id>|#<channel name>`, the value `SlackChannelPicker` reads and writes.
    slackChannel: string | null
    webhookUrl: string
}

export const EMPTY_DESTINATION_FORM: DestinationForm = {
    type: 'slack',
    slackWorkspaceId: null,
    slackChannel: null,
    webhookUrl: '',
}

export function validateDestinationForm(form: DestinationForm): Partial<Record<keyof DestinationForm, string>> {
    if (form.type === 'slack') {
        return form.slackChannel ? {} : { slackChannel: 'Pick a channel' }
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
        return destination.pagerduty_routing_key ? `Key ending ${destination.pagerduty_routing_key}` : ''
    }
    return destination.webhook_url ?? ''
}
