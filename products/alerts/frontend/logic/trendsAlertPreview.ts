import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

export interface TrendsAlertPreviewSeries {
    values: number[]
    labels?: string[]
    relative: boolean
}

interface AlertCheckPreviewInput {
    calculated_value: number | null
    created_at: string
}

export function deriveAlertCheckPreviewSeries(
    checks: AlertCheckPreviewInput[],
    conditionType: AlertConditionType,
    thresholdType: InsightThresholdType
): TrendsAlertPreviewSeries {
    const percentageChange =
        conditionType !== AlertConditionType.ABSOLUTE_VALUE && thresholdType === InsightThresholdType.PERCENTAGE
    const points = checks
        .filter(
            (check): check is AlertCheckPreviewInput & { calculated_value: number } =>
                check.calculated_value != null && Number.isFinite(check.calculated_value)
        )
        .sort((a, b) => a.created_at.localeCompare(b.created_at))

    return {
        values: points.map((check) => (percentageChange ? check.calculated_value * 100 : check.calculated_value)),
        labels: points.map((check) => check.created_at),
        relative: conditionType !== AlertConditionType.ABSOLUTE_VALUE,
    }
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
