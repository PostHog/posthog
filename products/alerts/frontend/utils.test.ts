import { AlertsTab, getActiveAlertsTab } from './utils'

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
