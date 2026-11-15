import { PropertyFilterType, PropertyOperator } from '~/types'

import { buildAlertFilterConfig, getAlertNotificationAddDisabledReason } from './alertNotifications'

describe('alertUtils', () => {
    describe('getAlertNotificationAddDisabledReason', () => {
        it.each([
            ['webhook', 'Enter a valid webhook URL'],
            ['discord', 'Enter a valid Discord webhook URL'],
            ['microsoft_teams', 'Enter a valid Microsoft Teams workflow URL'],
        ] as const)('rejects an invalid %s URL', (selectedType, expectedReason) => {
            expect(getAlertNotificationAddDisabledReason(selectedType, false, null, 'not a url', '')).toBe(
                expectedReason
            )
        })

        it('accepts a valid webhook URL', () => {
            expect(
                getAlertNotificationAddDisabledReason('webhook', false, null, 'https://example.com/webhook', '')
            ).toBeUndefined()
        })
    })

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
})
