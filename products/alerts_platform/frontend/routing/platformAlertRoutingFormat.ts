import { slackChannelId, slackChannelName } from 'lib/integrations/slackChannel'

import type {
    AlertReceiverApi,
    AlertReceiverWriteApi,
    AlertRouteApi,
    AlertRouteMatcherApi,
    PlatformAlertDestinationEventKindEnumApi,
} from '../generated/api.schemas'

export type ReceiverType = AlertReceiverApi['type']

export const RECEIVER_TYPE_OPTIONS: { value: ReceiverType; label: string }[] = [
    { value: 'slack', label: 'Slack' },
    { value: 'teams', label: 'Microsoft Teams' },
    { value: 'discord', label: 'Discord' },
    { value: 'webhook', label: 'Webhook' },
]

export const ROUTE_EVENT_KIND_OPTIONS: { value: PlatformAlertDestinationEventKindEnumApi; label: string }[] = [
    { value: 'firing', label: 'Firing' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'errored', label: 'Errored' },
    { value: 'broken', label: 'Broken' },
]

export const ALL_ROUTE_EVENT_KINDS = ROUTE_EVENT_KIND_OPTIONS.map((option) => option.value)

export interface ReceiverForm {
    name: string
    type: ReceiverType
    // Null picks the project's first Slack workspace.
    slackWorkspaceId: number | null
    // `<channel id>|#<channel name>`, the value `SlackChannelPicker` reads and writes.
    slackChannel: string | null
    webhookUrl: string
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
}
export const EMPTY_ROUTE_FORM: RouteForm = { receiverId: null, matchers: [], eventKinds: ALL_ROUTE_EVENT_KINDS }

export function receiverTypeLabel(type: ReceiverType): string {
    return RECEIVER_TYPE_OPTIONS.find((option) => option.value === type)?.label ?? type
}

export function receiverTarget(receiver: AlertReceiverApi): string {
    if (receiver.type === 'slack') {
        return `#${receiver.slack_channel_name || receiver.slack_channel_id}`
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
    return form.type !== 'slack' && editing?.type === form.type
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
            form.type !== 'slack' && !keepsStoredUrl(form, editing) && !form.webhookUrl.trim()
                ? 'Enter a webhook URL'
                : undefined,
    }
}

export function routeFormErrors(form: RouteForm): { receiverId?: string; eventKinds?: string } {
    // Conditions are checked by the API, which names the label at fault.
    return {
        receiverId: form.receiverId ? undefined : 'Choose a receiver',
        eventKinds: form.eventKinds.length ? undefined : 'Choose at least one event',
    }
}

export function trimmedMatchers(matchers: AlertRouteMatcherApi[]): AlertRouteMatcherApi[] {
    return matchers.map((matcher) => ({ label: matcher.label.trim(), value: matcher.value.trim() }))
}
