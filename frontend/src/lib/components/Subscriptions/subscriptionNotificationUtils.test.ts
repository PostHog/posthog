import { HogFunctionType } from '~/types'

import {
    PendingSubscriptionNotification,
    SUBSCRIPTION_DELIVERED_EVENT_ID,
    SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD,
    SUBSCRIPTION_NOTIFICATION_TYPE_SLACK,
    SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK,
    buildSubscriptionFilterConfig,
    buildSubscriptionHogFunctionPayload,
    firesForSubscription,
    isPinnedToSubscription,
} from './subscriptionNotificationUtils'

const hogFunctionWithSubscriptionId = (subscriptionId?: number): HogFunctionType =>
    ({
        filters:
            subscriptionId == null
                ? { events: [{ id: SUBSCRIPTION_DELIVERED_EVENT_ID, type: 'events' }] }
                : buildSubscriptionFilterConfig(subscriptionId),
    }) as HogFunctionType

describe('subscriptionNotificationUtils', () => {
    describe('buildSubscriptionFilterConfig', () => {
        it('pins the $subscription_delivered event to the subscription id', () => {
            const config = buildSubscriptionFilterConfig(42)
            expect(config.events).toEqual([{ id: SUBSCRIPTION_DELIVERED_EVENT_ID, type: 'events' }])
            expect(config.properties).toEqual([{ key: 'subscription_id', value: 42, operator: 'exact', type: 'event' }])
        })
    })

    describe('firesForSubscription', () => {
        it('matches team-wide (unpinned) destinations for any subscription', () => {
            expect(firesForSubscription(hogFunctionWithSubscriptionId(undefined), 42)).toBe(true)
        })
        it('matches a destination pinned to this subscription', () => {
            expect(firesForSubscription(hogFunctionWithSubscriptionId(42), 42)).toBe(true)
        })
        it('excludes a destination pinned to a different subscription', () => {
            expect(firesForSubscription(hogFunctionWithSubscriptionId(99), 42)).toBe(false)
        })
    })

    describe('isPinnedToSubscription', () => {
        it('is true only for a destination pinned to this subscription', () => {
            expect(isPinnedToSubscription(hogFunctionWithSubscriptionId(42), 42)).toBe(true)
            expect(isPinnedToSubscription(hogFunctionWithSubscriptionId(99), 42)).toBe(false)
            expect(isPinnedToSubscription(hogFunctionWithSubscriptionId(undefined), 42)).toBe(false)
        })
    })

    describe('buildSubscriptionHogFunctionPayload', () => {
        it.each([
            [
                'Slack',
                {
                    type: SUBSCRIPTION_NOTIFICATION_TYPE_SLACK,
                    slackWorkspaceId: 7,
                    slackChannelId: 'C123',
                    slackChannelName: 'general',
                },
                'template-slack',
            ],
            [
                'Slack without a channel name',
                { type: SUBSCRIPTION_NOTIFICATION_TYPE_SLACK, slackWorkspaceId: 7, slackChannelId: 'C123' },
                'template-slack',
            ],
            [
                'webhook',
                { type: SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK, webhookUrl: 'https://example.com/hook' },
                'template-webhook',
            ],
            [
                'Discord',
                { type: SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD, webhookUrl: 'https://discord.com/api/webhooks/x' },
                'template-discord',
            ],
        ])('builds a %s destination pinned to the subscription', (_label, notification, templateId) => {
            const payload = buildSubscriptionHogFunctionPayload(
                42,
                'Weekly report',
                notification as PendingSubscriptionNotification
            )
            expect(payload.template_id).toBe(templateId)
            expect(payload.filters).toEqual(buildSubscriptionFilterConfig(42))
        })

        it('carries channel + workspace for Slack and falls back to #channel without a channel name', () => {
            const named = buildSubscriptionHogFunctionPayload(42, 'R', {
                type: SUBSCRIPTION_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: 7,
                slackChannelId: 'C123',
                slackChannelName: 'general',
            })
            expect(named.inputs?.channel).toEqual({ value: 'C123' })
            expect(named.inputs?.slack_workspace).toEqual({ value: 7 })
            expect(named.name).toContain('#general')

            const unnamed = buildSubscriptionHogFunctionPayload(42, 'R', {
                type: SUBSCRIPTION_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: 7,
                slackChannelId: 'C123',
            })
            expect(unnamed.name).toContain('#channel')
        })

        it('carries the url and event-property body for a webhook', () => {
            const payload = buildSubscriptionHogFunctionPayload(42, undefined, {
                type: SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK,
                webhookUrl: 'https://example.com/hook',
            })
            expect(payload.inputs?.url).toEqual({ value: 'https://example.com/hook' })
            expect(payload.inputs?.body?.value).toMatchObject({
                subscription_name: '{event.properties.subscription_name}',
                summary: '{event.properties.summary}',
            })
        })

        it('carries the webhook url for Discord', () => {
            const payload = buildSubscriptionHogFunctionPayload(42, 'R', {
                type: SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD,
                webhookUrl: 'https://discord.com/api/webhooks/x',
            })
            expect(payload.inputs?.webhookUrl).toEqual({ value: 'https://discord.com/api/webhooks/x' })
        })
    })
})
