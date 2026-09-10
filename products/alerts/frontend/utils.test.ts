import {
    AlertState,
    ForecastConditionType,
    ForecastEngineType,
    ForecastTargetDirection,
} from '~/queries/schema/schema-general'

import type { AlertCheck, AlertCheckDelivery } from './types'
import type { AlertType } from './types'
import { AlertsTab, getActiveAlertsTab, isFailedDelivery, isTargetDatePassed, summarizeDeliveries } from './utils'

describe('alerts utils', () => {
    describe('isTargetDatePassed', () => {
        const targetAlert = (target_date: string, enabled: boolean): AlertType =>
            ({
                enabled,
                forecast_config: {
                    type: 'ForecastConfig',
                    engine: ForecastEngineType.PROPHET,
                    condition: ForecastConditionType.TARGET_BY_DATE,
                    target: 100,
                    target_direction: ForecastTargetDirection.AT_LEAST,
                    target_date,
                },
            }) as AlertType

        afterEach(() => {
            jest.useRealTimers()
        })

        const pinClock = (instant: string): void => {
            jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate'] }).setSystemTime(new Date(instant))
        }

        it.each([
            ['finished once the date passed', '2026-01-01', false, true],
            ['still running before the date', '2026-12-31', true, false],
            ['disabled by hand before the date', '2026-12-31', false, false],
            ['past date but still enabled', '2026-01-01', true, false],
            ['finished on the date itself', '2026-06-01', false, true],
            // The server accepts ISO week dates, which dayjs reads as an invalid date.
            ['a stored date the client cannot read', '2026-W40-1', false, false],
        ])('%s', (_name, date, enabled, expected) => {
            pinClock('2026-06-01T12:00:00Z')
            expect(isTargetDatePassed(targetAlert(date, enabled), 'UTC')).toBe(expected)
        })

        // Tests run on UTC, so each instant below puts the browser on the other side of midnight
        // from the project. Both rows fail if the browser calendar decides the verdict.
        it.each([
            ['a project that already reached the target date', '2026-06-01T20:00:00Z', 'Pacific/Auckland', true],
            ['a project that has not reached it yet', '2026-06-02T02:00:00Z', 'America/Los_Angeles', false],
        ])('reads the target date on the project calendar: %s', (_name, instant, timezone, expected) => {
            pinClock(instant)
            expect(isTargetDatePassed(targetAlert('2026-06-02', false), timezone)).toBe(expected)
        })

        it('is false for a non-target alert', () => {
            pinClock('2026-06-01T12:00:00Z')
            expect(isTargetDatePassed({ enabled: false } as AlertType, 'UTC')).toBe(false)
        })
    })

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
