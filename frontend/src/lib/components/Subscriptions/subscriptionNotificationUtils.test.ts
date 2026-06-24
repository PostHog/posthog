import { HogFunctionType } from '~/types'

import {
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
        it('builds a Slack destination pinned to the subscription with channel + workspace', () => {
            const payload = buildSubscriptionHogFunctionPayload(42, 'Weekly report', {
                type: SUBSCRIPTION_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: 7,
                slackChannelId: 'C123',
                slackChannelName: 'general',
            })
            expect(payload.template_id).toBe('template-slack')
            expect(payload.filters).toEqual(buildSubscriptionFilterConfig(42))
            expect(payload.inputs?.channel).toEqual({ value: 'C123' })
            expect(payload.inputs?.slack_workspace).toEqual({ value: 7 })
            expect(payload.name).toContain('Weekly report')
        })

        it('builds a webhook destination carrying the event properties', () => {
            const payload = buildSubscriptionHogFunctionPayload(42, undefined, {
                type: SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK,
                webhookUrl: 'https://example.com/hook',
            })
            expect(payload.template_id).toBe('template-webhook')
            expect(payload.inputs?.url).toEqual({ value: 'https://example.com/hook' })
            expect(payload.inputs?.body?.value).toMatchObject({
                subscription_name: '{event.properties.subscription_name}',
                summary: '{event.properties.summary}',
            })
        })

        it('builds a Discord destination from a webhook url', () => {
            const payload = buildSubscriptionHogFunctionPayload(42, 'R', {
                type: SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD,
                webhookUrl: 'https://discord.com/api/webhooks/x',
            })
            expect(payload.template_id).toBe('template-discord')
            expect(payload.inputs?.webhookUrl).toEqual({ value: 'https://discord.com/api/webhooks/x' })
        })
    })
})
