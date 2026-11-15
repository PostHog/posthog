import { pulseChange } from './todayPulseFacts'
import { makePulseMetric } from './todayTestFixtures'

describe('todayPulseFacts', () => {
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
