import { AlertState } from '~/queries/schema/schema-general'

import type { AlertCheck, AlertCheckDelivery } from './types'
import { AlertsTab, getActiveAlertsTab, isFailedDelivery, summarizeDeliveries } from './utils'

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
            {
                channel: 'email',
                target: 'a@example.com',
                status: 'accepted',
                at: '2026-08-11T00:00:00Z',
                display_label: 'Email: a@example.com',
            },
            {
                channel: 'hog_function',
                target: '#eng-alerts',
                template: 'slack',
                status: 'accepted',
                at: '2026-08-11T00:00:00Z',
                display_label: 'Slack #eng-alerts',
            },
        ]
        it('labels accepted receipts with their count and lines', () => {
            expect(summarizeDeliveries(accepted, true)).toEqual({
                kind: 'delivered',
                label: 'Yes · 2',
                lines: ['Email: a@example.com', 'Slack #eng-alerts'],
            })
        })

        it('still reports a check without receipts as notified', () => {
            expect(summarizeDeliveries(null, true)).toEqual({ kind: 'notified' })
        })

        it('returns none when nothing was recorded', () => {
            expect(summarizeDeliveries(null, false)).toEqual({ kind: 'none' })
            expect(summarizeDeliveries([], false)).toEqual({ kind: 'none' })
        })
    })

    describe('isFailedDelivery', () => {
        const check = (overrides: Partial<AlertCheck>): AlertCheck =>
            ({ state: AlertState.FIRING, ...overrides }) as AlertCheck

        it.each([
            { name: 'blames delivery for a plain firing check', overrides: {}, expected: true },
            {
                name: 'stays silent when the agent suppressed the notification',
                overrides: { notification_suppressed_by_agent: true },
                expected: false,
            },
            {
                name: 'stays silent while an investigation still gates the dispatch',
                overrides: { investigation_status: 'running' as const },
                expected: false,
            },
            {
                name: 'stays silent for a non-firing check',
                overrides: { state: AlertState.NOT_FIRING },
                expected: false,
            },
        ])('$name', ({ overrides, expected }) => {
            expect(isFailedDelivery(check(overrides))).toBe(expected)
        })
    })
})
