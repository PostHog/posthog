import { PropertyFilterType, PropertyOperator } from '~/types'

import { PendingAlertNotification, buildAlertFilterConfig, buildHogFunctionPayload } from './alertUtils'

describe('alertUtils', () => {
    describe('buildAlertFilterConfig', () => {
        it('builds filter config with the correct event and alert_id property', () => {
            const result = buildAlertFilterConfig('alert-123')

            expect(result).toEqual({
                properties: [
                    {
                        key: 'alert_id',
                        value: 'alert-123',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
                events: [
                    {
                        id: '$insight_alert_firing',
                        type: 'events',
                    },
                ],
            })
        })
    })

    describe('buildHogFunctionPayload', () => {
        it.each([
            {
                name: 'slack notification with alert name',
                notification: {
                    type: 'slack' as const,
                    slackWorkspaceId: 42,
                    slackChannelId: 'C12345|#general',
                    slackChannelName: 'general',
                },
                alertName: 'Daily revenue check',
                expectedName: 'Daily revenue check: Slack #general',
                expectedTemplateId: 'template-slack',
                expectedInputKeys: ['blocks', 'text', 'slack_workspace', 'channel'],
            },
            {
                name: 'slack notification without alert name',
                notification: {
                    type: 'slack' as const,
                    slackWorkspaceId: 42,
                    slackChannelId: 'C12345',
                },
                alertName: undefined,
                expectedName: 'Alert: Slack #channel',
                expectedTemplateId: 'template-slack',
                expectedInputKeys: ['blocks', 'text', 'slack_workspace', 'channel'],
            },
            {
                name: 'webhook notification',
                notification: {
                    type: 'webhook' as const,
                    webhookUrl: 'https://example.com/hook',
                },
                alertName: 'Spike detector',
                expectedName: 'Spike detector: Webhook https://example.com/hook',
                expectedTemplateId: 'template-webhook',
                expectedInputKeys: ['url', 'body'],
            },
        ])(
            'builds correct payload for $name',
            ({ notification, alertName, expectedName, expectedTemplateId, expectedInputKeys }) => {
                const result = buildHogFunctionPayload('alert-456', alertName, notification as PendingAlertNotification)

                expect(result.name).toBe(expectedName)
                expect(result.template_id).toBe(expectedTemplateId)
                expect(result.type).toBe('internal_destination')
                expect(result.enabled).toBe(true)
                expect(result.masking).toBeNull()
                expect(result.filters).toEqual(buildAlertFilterConfig('alert-456'))
                expect(Object.keys(result.inputs ?? {})).toEqual(expect.arrayContaining(expectedInputKeys))
            }
        )

        it('sets correct slack input values', () => {
            const notification: PendingAlertNotification = {
                type: 'slack',
                slackWorkspaceId: 42,
                slackChannelId: 'C12345|#general',
                slackChannelName: 'general',
            }

            const result = buildHogFunctionPayload('alert-789', 'My alert', notification)

            expect(result.inputs?.slack_workspace).toEqual({ value: 42 })
            expect(result.inputs?.channel).toEqual({ value: 'C12345|#general' })
        })

        it('sets correct webhook input values', () => {
            const notification: PendingAlertNotification = {
                type: 'webhook',
                webhookUrl: 'https://example.com/hook',
            }

            const result = buildHogFunctionPayload('alert-789', 'My alert', notification)

            expect(result.inputs?.url).toEqual({ value: 'https://example.com/hook' })
            expect(result.inputs?.body).toEqual({
                value: {
                    alert_name: '{event.properties.alert_name}',
                    insight_name: '{event.properties.insight_name}',
                    breaches: '{event.properties.breaches}',
                    insight_url: '{project.url}/insights/{event.properties.insight_id}',
                    alert_url:
                        '{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}',
                },
            })
        })
    })
})
