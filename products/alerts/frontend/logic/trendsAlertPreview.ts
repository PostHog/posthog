import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

export interface TrendsAlertPreviewSeries {
    values: number[]
    labels?: string[]
    relative: boolean
}

export function deriveTrendsAlertPreviewSeries(
    values: number[],
    labels: string[] | undefined,
    conditionType: AlertConditionType,
    thresholdType: InsightThresholdType
): TrendsAlertPreviewSeries {
    if (conditionType === AlertConditionType.ABSOLUTE_VALUE) {
        return { values, labels, relative: false }
    }

    const derivedValues = values.slice(1).map((current, index) => {
        const previous = values[index]
        const numerator =
            conditionType === AlertConditionType.RELATIVE_INCREASE ? current - previous : previous - current
        if (thresholdType === InsightThresholdType.ABSOLUTE) {
            return numerator
        }
        if (previous === 0) {
            return current === 0 ? 0 : Infinity
        }
        return (numerator / previous) * 100
    })

    return { values: derivedValues, labels: labels?.slice(1), relative: true }
}
