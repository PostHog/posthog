import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import {
    deriveAlertCheckPreviewSeries,
    deriveTrendsAlertPreviewSeries,
    deriveTrendsBreakdownAlertPreview,
} from './trendsAlertPreview'

describe('deriveTrendsAlertPreviewSeries', () => {
    it.each([
        [AlertConditionType.RELATIVE_INCREASE, InsightThresholdType.ABSOLUTE, [10, 15, 12], [5, -3], ['b', 'c']],
        [AlertConditionType.RELATIVE_DECREASE, InsightThresholdType.ABSOLUTE, [10, 15, 12], [-5, 3], ['b', 'c']],
        [AlertConditionType.RELATIVE_INCREASE, InsightThresholdType.PERCENTAGE, [100, 125, 100], [25, -20], ['b', 'c']],
        [AlertConditionType.RELATIVE_DECREASE, InsightThresholdType.PERCENTAGE, [100, 125, 100], [-25, 20], ['b', 'c']],
        [AlertConditionType.RELATIVE_INCREASE, InsightThresholdType.PERCENTAGE, [0, 1, 2], [100], ['c']],
    ])('mirrors backend %s evaluation with %s thresholds', (conditionType, thresholdType, values, expected, labels) => {
        expect(deriveTrendsAlertPreviewSeries(values, ['a', 'b', 'c'], conditionType, thresholdType)).toEqual({
            values: expected,
            labels,
            relative: true,
        })
    })

    it.each([
        [
            'moves a relative breakdown onto the compared intervals and gaps the rows that cannot compare',
            AlertConditionType.RELATIVE_INCREASE,
            InsightThresholdType.PERCENTAGE,
            [
                { key: '0', label: 'Chrome', data: [NaN, 100] },
                { key: '1', label: 'Safari', data: [100, 100] },
            ],
            ['b', 'c'],
        ],
        [
            'keeps an absolute breakdown on the raw intervals',
            AlertConditionType.ABSOLUTE_VALUE,
            InsightThresholdType.ABSOLUTE,
            [
                { key: '0', label: 'Chrome', data: [0, 4, 8] },
                { key: '1', label: 'Safari', data: [2, 4, 8] },
            ],
            ['a', 'b', 'c'],
        ],
    ])('%s', (_case, conditionType, thresholdType, rows, labels) => {
        expect(
            deriveTrendsBreakdownAlertPreview(
                [
                    { key: '0', label: 'Chrome', data: [0, 4, 8] },
                    { key: '1', label: 'Safari', data: [2, 4, 8] },
                ],
                ['a', 'b', 'c'],
                conditionType,
                thresholdType
            )
        ).toEqual({ rows, labels })
    })

    it('returns an empty series when checks is undefined', () => {
        expect(
            deriveAlertCheckPreviewSeries(undefined, AlertConditionType.ABSOLUTE_VALUE, InsightThresholdType.ABSOLUTE)
        ).toEqual({
            values: [],
            labels: [],
            relative: false,
        })
    })

    it('builds a chronological percentage preview from completed alert checks', () => {
        expect(
            deriveAlertCheckPreviewSeries(
                [
                    { created_at: '2026-07-21T12:00:00Z', calculated_value: 0.25 },
                    { created_at: '2026-07-21T10:00:00Z', calculated_value: null },
                    { created_at: '2026-07-21T11:00:00Z', calculated_value: 0.1 },
                ],
                AlertConditionType.RELATIVE_INCREASE,
                InsightThresholdType.PERCENTAGE
            )
        ).toEqual({
            values: [10, 25],
            labels: ['2026-07-21T11:00:00Z', '2026-07-21T12:00:00Z'],
            relative: true,
        })
    })
})
