import type { AlertCheckDelivery } from './types'
import { AlertsTab, getActiveAlertsTab, summarizeDeliveries } from './utils'

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

    describe('summarizeDeliveries', () => {
        const accepted: AlertCheckDelivery[] = [
            { channel: 'email', target: 'a@example.com', status: 'accepted', display_label: 'Email: a@example.com' },
            {
                channel: 'hog_function',
                target: '#eng-alerts',
                template: 'slack',
                status: 'accepted',
                display_label: 'Slack #eng-alerts',
            },
        ]
        const legacy: AlertCheckDelivery[] = [
            { channel: 'email', target: 'a@example.com', status: 'unknown', display_label: 'Email: a@example.com' },
        ]

        it('labels accepted receipts with their count and lines', () => {
            expect(summarizeDeliveries(accepted, true)).toEqual({
                kind: 'delivered',
                label: 'Yes · 2',
                lines: ['Email: a@example.com', 'Slack #eng-alerts'],
            })
        })

        it('marks unknown-only receipts as legacy with their targets', () => {
            expect(summarizeDeliveries(legacy, true)).toEqual({
                kind: 'legacy',
                label: 'Yes',
                lines: ['Email: a@example.com'],
            })
        })

        it('marks legacy rows without receipts from the boolean alone', () => {
            expect(summarizeDeliveries(null, true)).toEqual({ kind: 'legacy', label: 'Yes', lines: [] })
        })

        it('returns none when nothing was recorded', () => {
            expect(summarizeDeliveries(null, false)).toEqual({ kind: 'none' })
            expect(summarizeDeliveries([], false)).toEqual({ kind: 'none' })
        })
    })
})
