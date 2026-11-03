import { dayjs } from 'lib/dayjs'

import { pulseChange, pulseWhy } from './todayPulseFacts'
import { makePulseMetric } from './todayTestFixtures'

describe('todayPulseFacts', () => {
    const today = dayjs('2026-09-30T10:00:00')

    it.each([
        [
            'an insight opened on several days',
            { reason: 'routine', opened_days: 5, last_opened: '2026-09-29' },
            'You opened this insight on 5 of the last 14 days, most recently yesterday.',
        ],
        [
            'an insight opened once',
            { reason: 'routine', opened_days: 1, last_opened: '2026-09-21' },
            'You last opened this insight on Sep 21.',
        ],
        [
            'a dashboard tile opened today',
            { reason: 'dashboard', dashboard_name: 'Growth', opened_days: 9, last_opened: '2026-09-30' },
            'You opened the Growth dashboard on 9 of the last 14 days, most recently today. This is the first chart on that dashboard.',
        ],
        [
            'a key metric',
            { reason: 'key_metric', opened_days: null, last_opened: null },
            'It is a key metric for this project, set in Customer analytics.',
        ],
        ['a metric computed before reasons existed', { reason: null }, null],
    ] as const)('explains %s', (_name, overrides, expected) => {
        expect(pulseWhy(makePulseMetric(overrides), today)).toBe(expected)
    })

    it.each([
        ['a count', { value: 120, previous_value: 100, change_pct: 20, value_format: null }, { value: 20, unit: '%' }],
        [
            'a 0-100 rate',
            {
                value: 3.4,
                previous_value: 3,
                change_pct: 13.3,
                value_format: { format: 'percentage', prefix: null, postfix: null, decimal_places: 1 },
            },
            { value: 3.4 - 3, unit: 'pp' },
        ],
        [
            'a 0-1 rate',
            {
                value: 0.25,
                previous_value: 0.2,
                change_pct: 25,
                value_format: { format: 'percentage_scaled', prefix: null, postfix: null, decimal_places: 1 },
            },
            { value: (0.25 - 0.2) * 100, unit: 'pp' },
        ],
        [
            'a rate that starts from zero',
            {
                value: 5,
                previous_value: 0,
                change_pct: null,
                value_format: { format: 'percentage', prefix: null, postfix: null, decimal_places: 1 },
            },
            { value: 5, unit: 'pp' },
        ],
        [
            'a rate with no earlier period',
            {
                value: 5,
                previous_value: null,
                change_pct: null,
                value_format: { format: 'percentage', prefix: null, postfix: null, decimal_places: 1 },
            },
            { value: null, unit: 'pp' },
        ],
    ] as const)('measures the change of %s', (_name, overrides, expected) => {
        expect(pulseChange(makePulseMetric(overrides))).toEqual(expected)
    })
})
