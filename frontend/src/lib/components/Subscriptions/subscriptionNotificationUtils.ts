import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import { CyclotronJobFiltersType, HogFunctionType, PropertyFilterType, PropertyOperator } from '~/types'

export const SUBSCRIPTION_DELIVERED_EVENT_ID = '$subscription_delivered'
export const SUBSCRIPTION_DELIVERED_SUB_TEMPLATE_ID = 'subscription-delivered'

export const SUBSCRIPTION_NOTIFICATION_TYPE_SLACK = 'slack' as const
export const SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK = 'webhook' as const
export const SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD = 'discord' as const
export type SubscriptionNotificationType =
    | typeof SUBSCRIPTION_NOTIFICATION_TYPE_SLACK
    | typeof SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK
    | typeof SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD

export type PendingSubscriptionNotification =
    | {
          type: typeof SUBSCRIPTION_NOTIFICATION_TYPE_SLACK
          slackWorkspaceId: number
          slackChannelId: string
          slackChannelName?: string
      }
    | {
          type: typeof SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK
          webhookUrl: string
      }
    | {
          type: typeof SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD
          webhookUrl: string
      }

// Filter group pinning a destination to one subscription's deliveries (mirrors buildAlertFilterConfig).
export const buildSubscriptionFilterConfig = (subscriptionId: number): CyclotronJobFiltersType => ({
    properties: [
        {
            key: 'subscription_id',
            value: subscriptionId,
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        },
    ],
    events: [{ id: SUBSCRIPTION_DELIVERED_EVENT_ID, type: 'events' }],
})

// A destination "fires for this subscription" if it has no subscription_id pin (team-wide) or pins this id.
export const firesForSubscription = (hogFunction: HogFunctionType, subscriptionId: number): boolean => {
    const pinned = (hogFunction.filters?.properties ?? []).find((p) => 'key' in p && p.key === 'subscription_id')
    return !pinned || String(pinned.value) === String(subscriptionId)
}

export const isPinnedToSubscription = (hogFunction: HogFunctionType, subscriptionId: number): boolean => {
    const pinned = (hogFunction.filters?.properties ?? []).find((p) => 'key' in p && p.key === 'subscription_id')
    return !!pinned && String(pinned.value) === String(subscriptionId)
}

const SLACK_INPUTS =
    HOG_FUNCTION_SUB_TEMPLATES[SUBSCRIPTION_DELIVERED_SUB_TEMPLATE_ID].find((t) => t.template_id === 'template-slack')
        ?.inputs ?? {}

const DISCORD_INPUTS =
    HOG_FUNCTION_SUB_TEMPLATES[SUBSCRIPTION_DELIVERED_SUB_TEMPLATE_ID].find((t) => t.template_id === 'template-discord')
        ?.inputs ?? {}

export function buildSubscriptionHogFunctionPayload(
    subscriptionId: number,
    subscriptionName: string | undefined,
    notification: PendingSubscriptionNotification
): Partial<HogFunctionType> {
    const commonProps = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[SUBSCRIPTION_DELIVERED_SUB_TEMPLATE_ID]
    const label = subscriptionName || 'Subscription'
    const base = {
        type: commonProps.type,
        enabled: true,
        masking: null,
        filters: buildSubscriptionFilterConfig(subscriptionId),
    }

    if (notification.type === SUBSCRIPTION_NOTIFICATION_TYPE_SLACK) {
        return {
            ...base,
            name: `${label}: Slack #${notification.slackChannelName ?? 'channel'}`,
            template_id: 'template-slack',
            inputs: {
                ...SLACK_INPUTS,
                slack_workspace: { value: notification.slackWorkspaceId },
                channel: { value: notification.slackChannelId },
            },
        }
    }

    if (notification.type === SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD) {
        return {
            ...base,
            name: `${label}: Discord`,
            template_id: 'template-discord',
            inputs: {
                ...DISCORD_INPUTS,
                webhookUrl: { value: notification.webhookUrl },
            },
        }
    }

    return {
        ...base,
        name: `${label}: Webhook ${notification.webhookUrl}`,
        template_id: 'template-webhook',
        inputs: {
            url: { value: notification.webhookUrl },
            body: {
                value: {
                    subscription_name: '{event.properties.subscription_name}',
                    target_type: '{event.properties.target_type}',
                    resource_type: '{event.properties.resource_type}',
                    recipient_count: '{event.properties.recipient_count}',
                    summary: '{event.properties.summary}',
                    subscription_url: '{event.properties.subscription_url}',
                },
            },
        },
    }
}
