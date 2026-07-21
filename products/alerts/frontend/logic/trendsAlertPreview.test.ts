import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { deriveAlertCheckPreviewSeries, deriveTrendsAlertPreviewSeries } from './trendsAlertPreview'

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
