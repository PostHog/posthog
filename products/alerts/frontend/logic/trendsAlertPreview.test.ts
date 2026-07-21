import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { deriveTrendsAlertPreviewSeries } from './trendsAlertPreview'

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
})
