import type { BillingAlertConfig } from 'scenes/billing/billingLogic'

import { TodayRailSeverity, severityFromBillingAlert, worstSeverity } from './todayRailSeverity'

describe('todayRailSeverity', () => {
    test.each<[string, BillingAlertConfig | null, TodayRailSeverity]>([
        ['no alert', null, 'none'],
        ['usage limit reached', { kind: 'usage_limit', status: 'error', title: '' }, 'critical'],
        ['usage limit approaching', { kind: 'usage_limit', status: 'info', title: '' }, 'warning'],
        ['trial ending', { kind: 'trial', status: 'info', title: '' }, 'none'],
    ])('rates a billing alert for %s', (_name, alert, expected) => {
        expect(severityFromBillingAlert(alert)).toEqual(expected)
    })

    test.each<[TodayRailSeverity[], TodayRailSeverity]>([
        [['ok', 'warning'], 'warning'],
        [['critical', 'notice'], 'critical'],
        [['none', 'notice'], 'notice'],
    ])('picks the worst of %j', (severities, expected) => {
        expect(worstSeverity(...severities)).toEqual(expected)
    })
})
