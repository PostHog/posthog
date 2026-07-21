import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { formatNotificationSummary, formatThresholdSummary } from './alertSummary'

describe('alertSummary', () => {
    it.each([
        [0, 0, ''],
        [1, 0, '1 person'],
        [0, 1, '1 destination'],
        [3, 2, '3 people + 2 destinations'],
    ])('summarizes %i people and %i destinations', (subscribedCount, destinationCount, expected) => {
        expect(formatNotificationSummary(subscribedCount, destinationCount)).toBe(expected)
    })

    it.each([
        [AlertConditionType.RELATIVE_INCREASE, InsightThresholdType.PERCENTAGE, 0, 0.1, 'increase outside 0% – 10%'],
        [AlertConditionType.RELATIVE_INCREASE, InsightThresholdType.ABSOLUTE, undefined, 10, 'increase above 10'],
        [AlertConditionType.RELATIVE_DECREASE, InsightThresholdType.PERCENTAGE, 0.05, undefined, 'decrease below 5%'],
    ])('summarizes %s bounds using %s units', (conditionType, thresholdType, lower, upper, expected) => {
        expect(formatThresholdSummary(conditionType, thresholdType, lower, upper)).toBe(expected)
    })
})
