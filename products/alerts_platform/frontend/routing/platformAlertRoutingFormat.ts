import { combineUrl } from 'kea-router'

import { slackChannelId, slackChannelName } from 'lib/integrations/slackChannel'
import { urls } from 'scenes/urls'

import type {
    AlertReceiverApi,
    AlertReceiverWriteApi,
    AlertRouteApi,
    AlertRouteMatcherApi,
    PagerDutyRegionEnumApi,
    PagerDutySeverityEnumApi,
    PlatformAlertDestinationEventKindEnumApi,
} from '../generated/api.schemas'

export type ReceiverType = AlertReceiverApi['type']

export const RECEIVER_TYPE_OPTIONS: { value: ReceiverType; label: string }[] = [
    { value: 'slack', label: 'Slack' },
    { value: 'teams', label: 'Microsoft Teams' },
    { value: 'discord', label: 'Discord' },
    { value: 'webhook', label: 'Webhook' },
    { value: 'pagerduty', label: 'PagerDuty' },
]

export const PAGERDUTY_SEVERITY_OPTIONS: { value: PagerDutySeverityEnumApi; label: string }[] = [
    { value: 'critical', label: 'Critical' },
    { value: 'error', label: 'Error' },
    { value: 'warning', label: 'Warning' },
    { value: 'info', label: 'Info' },
]

export const PAGERDUTY_REGION_OPTIONS: { value: PagerDutyRegionEnumApi; label: string }[] = [
    { value: 'us', label: 'US' },
    { value: 'eu', label: 'EU' },
]

export const ROUTE_EVENT_KIND_OPTIONS: { value: PlatformAlertDestinationEventKindEnumApi; label: string }[] = [
    { value: 'firing', label: 'Firing' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'errored', label: 'Errored' },
    { value: 'broken', label: 'Broken' },
]

export const ALL_ROUTE_EVENT_KINDS = ROUTE_EVENT_KIND_OPTIONS.map((option) => option.value)

export function routeEventKindsLabel(kinds: PlatformAlertDestinationEventKindEnumApi[]): string {
    return kinds.length === ALL_ROUTE_EVENT_KINDS.length
        ? 'All'
        : ROUTE_EVENT_KIND_OPTIONS.filter((option) => kinds.includes(option.value))
              .map((option) => option.label)
              .join(', ')
}

// pinned: `tab`, `route` and `receiver` search params are shareable links into the routing tab
export function routingUrl(highlight: { route?: string; receiver?: string } = {}): string {
    return combineUrl(urls.platformAlerts(), { tab: 'routing', ...highlight }).url
}

export interface ReceiverForm {
    name: string
    type: ReceiverType
    // Null picks the project's first Slack workspace.
    slackWorkspaceId: number | null
    // `<channel id>|#<channel name>`, the value `SlackChannelPicker` reads and writes.
    slackChannel: string | null
    webhookUrl: string
    pagerdutyRoutingKey: string
    pagerdutySeverity: PagerDutySeverityEnumApi
    pagerdutyRegion: PagerDutyRegionEnumApi
}

export interface RouteForm {
    receiverId: string | null
    matchers: AlertRouteMatcherApi[]
    eventKinds: PlatformAlertDestinationEventKindEnumApi[]
}

export const EMPTY_RECEIVER_FORM: ReceiverForm = {
    name: '',
    type: 'slack',
    slackWorkspaceId: null,
    slackChannel: null,
    webhookUrl: '',
    pagerdutyRoutingKey: '',
    pagerdutySeverity: 'critical',
    pagerdutyRegion: 'us',
}
export const EMPTY_ROUTE_FORM: RouteForm = { receiverId: null, matchers: [], eventKinds: ALL_ROUTE_EVENT_KINDS }

export function receiverTypeLabel(type: ReceiverType): string {
    return RECEIVER_TYPE_OPTIONS.find((option) => option.value === type)?.label ?? type
}

export function receiverTarget(receiver: AlertReceiverApi): string {
    if (receiver.type === 'slack') {
        return `#${receiver.slack_channel_name || receiver.slack_channel_id}`
    }
    if (receiver.type === 'pagerduty') {
        return `Integration key ${receiver.pagerduty_routing_key ?? ''}`
    }
    return receiver.webhook_url ?? ''
}

export function receiverFormFor(receiver: AlertReceiverApi): ReceiverForm {
    return {
        name: receiver.name,
        type: receiver.type,
        slackWorkspaceId: receiver.slack_workspace_id ?? null,
        slackChannel:
            receiver.type === 'slack' && receiver.slack_channel_id
                ? `${receiver.slack_channel_id}|#${receiver.slack_channel_name || receiver.slack_channel_id}`
                : null,
        // Reads return the URL without its secret path, so an edit starts blank and keeps the stored URL.
        webhookUrl: '',
        // Reads return the last four characters of the key, so an edit starts blank and keeps the stored key.
        pagerdutyRoutingKey: '',
        pagerdutySeverity: receiver.pagerduty_severity ?? 'critical',
        pagerdutyRegion: receiver.pagerduty_region ?? 'us',
    }
}

export function routeFormFor(route: AlertRouteApi): RouteForm {
    return {
        receiverId: route.receiver_id,
        matchers: route.matchers,
        eventKinds: route.event_kinds,
    }
}

/** An edit to a webhook-style receiver of the same type may leave the URL blank, because reads return it redacted. */
export function keepsStoredUrl(form: ReceiverForm, editing: AlertReceiverApi | null): boolean {
    return form.type !== 'slack' && form.type !== 'pagerduty' && editing?.type === form.type
}

/** An edit to a PagerDuty receiver may leave the key blank to keep it, but only while the severity and region stay
 * as stored: the API replaces the whole destination, and it cannot send the stored key back. */
export function keepsStoredKey(form: ReceiverForm, editing: AlertReceiverApi | null): boolean {
    return (
        form.type === 'pagerduty' &&
        editing?.type === 'pagerduty' &&
        form.pagerdutySeverity === (editing.pagerduty_severity ?? 'critical') &&
        form.pagerdutyRegion === (editing.pagerduty_region ?? 'us')
    )
}

/** Null when an edit leaves the stored destination as it is. */
export function receiverDestinationBody(
    form: ReceiverForm,
    slackWorkspaceId: number | undefined,
    editing: AlertReceiverApi | null
): Omit<AlertReceiverWriteApi, 'name' | 'enabled'> | null {
    if (form.type === 'slack') {
        const channelId = slackChannelId(form.slackChannel ?? '')
        if (
            editing?.type === 'slack' &&
            editing.slack_channel_id === channelId &&
            editing.slack_workspace_id === slackWorkspaceId
        ) {
            return null
        }
        return {
            type: 'slack',
            slack_workspace_id: slackWorkspaceId,
            slack_channel_id: channelId,
            slack_channel_name: slackChannelName(form.slackChannel ?? '') ?? channelId,
        }
    }
    if (form.type === 'pagerduty') {
        const routingKey = form.pagerdutyRoutingKey.trim()
        if (keepsStoredKey(form, editing) && !routingKey) {
            return null
        }
        return {
            type: 'pagerduty',
            pagerduty_routing_key: routingKey,
            pagerduty_severity: form.pagerdutySeverity,
            pagerduty_region: form.pagerdutyRegion,
        }
    }
    const webhookUrl = form.webhookUrl.trim()
    if (keepsStoredUrl(form, editing) && !webhookUrl) {
        return null
    }
    return { type: form.type, webhook_url: webhookUrl }
}

export function receiverFormErrors(
    form: ReceiverForm,
    editing: AlertReceiverApi | null
): Partial<Record<keyof ReceiverForm, string>> {
    return {
        name: form.name.trim() ? undefined : 'Enter a name',
        slackChannel: form.type === 'slack' && !form.slackChannel ? 'Choose a channel' : undefined,
        webhookUrl:
            form.type !== 'slack' &&
            form.type !== 'pagerduty' &&
            !keepsStoredUrl(form, editing) &&
            !form.webhookUrl.trim()
                ? 'Enter a webhook URL'
                : undefined,
        pagerdutyRoutingKey:
            form.type === 'pagerduty' && !keepsStoredKey(form, editing) && !form.pagerdutyRoutingKey.trim()
                ? editing?.type === 'pagerduty'
                    ? 'Enter the integration key again to change the severity or region'
                    : 'Enter an integration key'
                : undefined,
    }
}

export function receiverTypeOf(
    receivers: AlertReceiverApi[] | null,
    receiverId: string | null
): ReceiverType | undefined {
    return receivers?.find((receiver) => receiver.id === receiverId)?.type
}

/** An incident manager hears every trigger and resolve, so the events a route lists change nothing for it. */
export function opensIncidents(type: ReceiverType | undefined): boolean {
    return type === 'pagerduty'
}

export function routeFormErrors(
    form: RouteForm,
    receiverType: ReceiverType | undefined
): { receiverId?: string; eventKinds?: string } {
    // Conditions are checked by the API, which names the label at fault.
    return {
        receiverId: form.receiverId ? undefined : 'Choose a receiver',
        // The event options are hidden for an incident manager, so an error there could not be seen or fixed.
        eventKinds: form.eventKinds.length || opensIncidents(receiverType) ? undefined : 'Choose at least one event',
    }
}

export function trimmedMatchers(matchers: AlertRouteMatcherApi[]): AlertRouteMatcherApi[] {
    return matchers.map((matcher) => ({ label: matcher.label.trim(), value: matcher.value.trim() }))
}
