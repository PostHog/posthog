import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

export interface TrendsAlertPreviewSeries {
    values: number[]
    labels?: string[]
    relative: boolean
}

export interface TrendsBreakdownAlertPreviewRow {
    key: string
    label: string
    data: number[]
}

export interface TrendsBreakdownAlertPreview {
    rows: TrendsBreakdownAlertPreviewRow[]
    labels?: string[]
}

interface AlertCheckPreviewInput {
    calculated_value: number | null
    created_at: string
}

interface DerivedPoint {
    value: number | null
    index: number
}

export function deriveAlertCheckPreviewSeries(
    checks: AlertCheckPreviewInput[] | undefined,
    conditionType: AlertConditionType,
    thresholdType: InsightThresholdType
): TrendsAlertPreviewSeries {
    const percentageChange =
        conditionType !== AlertConditionType.ABSOLUTE_VALUE && thresholdType === InsightThresholdType.PERCENTAGE
    const points = (checks ?? [])
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

/** One point per interval transition, kept in raw interval order. `index` is the position of the
 *  earlier interval. A `null` value marks a percentage change that has no meaning because the
 *  earlier interval was zero. */
function deriveRelativePoints(
    values: number[],
    conditionType: AlertConditionType,
    thresholdType: InsightThresholdType
): DerivedPoint[] {
    return values.slice(1).map((current, index) => {
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

    const availablePoints = deriveRelativePoints(values, conditionType, thresholdType).filter(
        (point): point is { value: number; index: number } => point.value !== null
    )

    return {
        values: availablePoints.map((point) => point.value),
        labels: labels ? availablePoints.map((point) => labels[point.index + 1]) : undefined,
        relative: true,
    }
}

/** The breakdown rows and the one set of labels they all sit on. A relative point compares an
 *  interval to the one before it, so it belongs to the later interval and the first raw label names
 *  no point. A row without a usable comparison for an interval gets `NaN` there, which the chart
 *  draws as a gap. Every row needs the same grid: if each row instead dropped its own unusable
 *  comparisons, rows with different numbers of comparisons would put different intervals on the same
 *  x position. */
export function deriveTrendsBreakdownAlertPreview(
    series: TrendsBreakdownAlertPreviewRow[] | undefined,
    labels: string[] | undefined,
    conditionType: AlertConditionType,
    thresholdType: InsightThresholdType
): TrendsBreakdownAlertPreview | null {
    if (!series) {
        return null
    }
    const relative = conditionType !== AlertConditionType.ABSOLUTE_VALUE

    return {
        // Trend results declare `data` as a required array, but breakdown rows can arrive without it.
        rows: series
            .filter(({ data }) => Array.isArray(data))
            .map(({ key, label, data }) => ({
                key,
                label,
                data: relative
                    ? deriveRelativePoints(data, conditionType, thresholdType).map((point) => point.value ?? NaN)
                    : data,
            })),
        labels: relative ? labels?.slice(1) : labels,
    }
}
