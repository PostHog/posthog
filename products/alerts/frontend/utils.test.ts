import type { AlertCheckDelivery } from './types'
import { AlertsTab, describeDelivery, getActiveAlertsTab } from './utils'

describe('alerts utils', () => {
    describe('getActiveAlertsTab', () => {
        it.each([
            {
                name: 'defaults to log alerts for a logs-only user',
                alertId: null,
                requestedTab: undefined,
                canViewInsightAlerts: false,
                canViewLogAlerts: true,
                expected: AlertsTab.LOGS,
            },
            {
                name: 'denies access when neither alert type is available',
                alertId: null,
                requestedTab: undefined,
                canViewInsightAlerts: false,
                canViewLogAlerts: false,
                expected: null,
            },
            {
                name: 'denies an insight alert deep link for a logs-only user',
                alertId: 'alert-id',
                requestedTab: undefined,
                canViewInsightAlerts: false,
                canViewLogAlerts: true,
                expected: null,
            },
            {
                name: 'falls back to insight alerts when log alerts are unavailable',
                alertId: null,
                requestedTab: AlertsTab.LOGS,
                canViewInsightAlerts: true,
                canViewLogAlerts: false,
                expected: AlertsTab.INSIGHTS,
            },
        ])('$name', ({ name: _, expected, ...state }) => {
            expect(getActiveAlertsTab(state)).toBe(expected)
        })
    })

    describe('describeDelivery', () => {
        it.each([
            [{ channel: 'email', target: 'a@example.com', status: 'accepted' }, 'Email: a@example.com'],
            [
                { channel: 'hog_function', target: 'Eng alerts', template: 'slack', status: 'accepted' },
                'Slack: Eng alerts',
            ],
            [
                { channel: 'hog_function', target: 'My endpoint', template: 'webhook', status: 'accepted' },
                'Webhook: My endpoint',
            ],
            [
                { channel: 'hog_function', target: 'Mystery', template: null, status: 'accepted' },
                'Destination: Mystery',
            ],
            [{ channel: 'in_app', target: 'user:1', status: 'accepted' }, 'in_app: user:1'],
        ])('formats %j', (delivery, expected) => {
            expect(describeDelivery(delivery as AlertCheckDelivery)).toBe(expected)
        })
    })
})
