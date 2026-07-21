import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { deriveAlertCheckPreviewSeries, deriveTrendsAlertPreviewSeries } from './trendsAlertPreview'

describe('deriveTrendsAlertPreviewSeries', () => {
    it.each([
        [AlertConditionType.RELATIVE_INCREASE, InsightThresholdType.ABSOLUTE, [10, 15, 12], [5, -3]],
        [AlertConditionType.RELATIVE_DECREASE, InsightThresholdType.ABSOLUTE, [10, 15, 12], [-5, 3]],
        [AlertConditionType.RELATIVE_INCREASE, InsightThresholdType.PERCENTAGE, [100, 125, 100], [25, -20]],
        [AlertConditionType.RELATIVE_DECREASE, InsightThresholdType.PERCENTAGE, [100, 125, 100], [-25, 20]],
    ])('mirrors backend %s evaluation with %s thresholds', (conditionType, thresholdType, values, expected) => {
        expect(deriveTrendsAlertPreviewSeries(values, ['a', 'b', 'c'], conditionType, thresholdType)).toEqual({
            values: expected,
            labels: ['b', 'c'],
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
