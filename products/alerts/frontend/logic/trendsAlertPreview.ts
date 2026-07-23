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

    const derivedPoints = values.slice(1).map((current, index) => {
        const previous = values[index]
        const numerator =
            conditionType === AlertConditionType.RELATIVE_INCREASE ? current - previous : previous - current
        if (thresholdType === InsightThresholdType.ABSOLUTE) {
            return { value: numerator, index }
        }
        if (previous === 0) {
            return { value: current === 0 ? 0 : null, index }
        }
        return { value: (numerator / previous) * 100, index }
    })
    const availablePoints = derivedPoints.filter(
        (point): point is { value: number; index: number } => point.value !== null
    )

    return {
        values: availablePoints.map((point) => point.value),
        labels: labels ? availablePoints.map((point) => labels[point.index + 1]) : undefined,
        relative: true,
    }
}
