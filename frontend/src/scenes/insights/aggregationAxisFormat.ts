import posthog from 'posthog-js'

import { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { formatCurrency } from 'lib/utils/currency'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { compactNumber, humanFriendlyCurrency, humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'
import { ChartDisplayType, TrendsFilterType } from '~/types'

const formats = ['numeric', 'duration', 'duration_ms', 'percentage', 'percentage_scaled', 'currency', 'short'] as const
export type AggregationAxisFormat = (typeof formats)[number]

export const INSIGHT_UNIT_OPTIONS: LemonSelectOptionLeaf<AggregationAxisFormat>[] = [
    { value: 'numeric', label: 'None' },
    { value: 'duration', label: 'Duration (s)' },
    { value: 'duration_ms', label: 'Duration (ms)' },
    { value: 'percentage', label: 'Percent (0-100)' },
    { value: 'percentage_scaled', label: 'Percent (0-1)' },
    { value: 'currency', label: 'Currency ($)' },
    { value: 'short', label: 'Short Number' },
]

// The Metric display type reads as a single headline number, so it defaults to short numbers (e.g. "1.2k");
// other displays have no default unit. Returns the format to fall back to when none is explicitly set.
export const defaultAggregationAxisFormatForDisplay = (
    display: ChartDisplayType | null | undefined
): AggregationAxisFormat | undefined => (display === ChartDisplayType.Metric ? 'short' : undefined)

export const INSIGHT_UNIT_OPTIONS_SHORT: Record<AggregationAxisFormat, string> = {
    numeric: '',
    duration: 's',
    duration_ms: 'ms',
    percentage: '%',
    percentage_scaled: '%',
    currency: '$',
    short: 'Short',
}
// this function needs to support a trendsFilter as part of an insight query and
// legacy trend filters, as we still return these as part of a data response
export const formatAggregationAxisValue = (
    trendsFilter: TrendsFilter | null | undefined | Partial<TrendsFilterType>,
    value: number | string,
    currency?: CurrencyCode
): string => {
    value = Number(value)
    const maxDecimalPlaces =
        (trendsFilter as TrendsFilter)?.decimalPlaces ?? (trendsFilter as Partial<TrendsFilterType>)?.decimal_places
    const minDecimalPlaces =
        (trendsFilter as TrendsFilter)?.minDecimalPlaces ??
        (trendsFilter as Partial<TrendsFilterType>)?.min_decimal_places
    const aggregationAxisFormat =
        (trendsFilter as TrendsFilter)?.aggregationAxisFormat ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_format
    const aggregationAxisPrefix =
        (trendsFilter as TrendsFilter)?.aggregationAxisPrefix ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_prefix
    const aggregationAxisPostfix =
        (trendsFilter as TrendsFilter)?.aggregationAxisPostfix ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_postfix
    let formattedValue = humanFriendlyNumber(value, maxDecimalPlaces, minDecimalPlaces)
    if (aggregationAxisFormat) {
        switch (aggregationAxisFormat) {
            case 'duration':
                formattedValue = humanFriendlyDuration(value)
                break
            case 'duration_ms':
                formattedValue = humanFriendlyDuration(value / 1000, { secondsFixed: 1 })
                break
            case 'percentage':
                formattedValue = percentage(value / 100, maxDecimalPlaces)
                break
            case 'percentage_scaled':
                formattedValue = percentage(value, maxDecimalPlaces)
                break
            case 'currency':
                // In the rare case where we get an error because we have an invalid currency code
                // let's make sure we fallback to the human friendly one
                try {
                    formattedValue = currency ? formatCurrency(value, currency) : humanFriendlyCurrency(value)
                } catch (error) {
                    posthog.captureException(error, { value, currency })
                    formattedValue = humanFriendlyCurrency(value)
                }
                break
            case 'short':
                formattedValue = compactNumber(value)
                break
            case 'numeric': // numeric is default
            default:
                break
        }
    }
    // Skip the prefix only for currency format, where the symbol is already embedded in the formatted value
    // (e.g. currency "$" + prefix "$" → "$$"). Other formats keep their prefix even if it shares a leading char.
    const effectivePrefix =
        aggregationAxisFormat === 'currency' &&
        aggregationAxisPrefix &&
        formattedValue.startsWith(aggregationAxisPrefix)
            ? ''
            : aggregationAxisPrefix || ''
    return `${effectivePrefix}${formattedValue}${aggregationAxisPostfix || ''}`
}

export const formatPercentStackAxisValue = (
    trendsFilter: TrendsFilter | null | undefined | Partial<TrendsFilterType>,
    value: number | string,
    isPercentStackView: boolean,
    currency?: CurrencyCode
): string => {
    if (isPercentStackView) {
        value = Number(value)
        return percentage(value / 100)
    }

    return formatAggregationAxisValue(trendsFilter, value, currency)
}

// Formats a value and appends its share of the total, e.g. "1,234 (37.5%)".
// Skips the share-of-total suffix when the axis is already formatted as a percentage
// to avoid confusing output like "37% (60%)" (metric value vs share of total).
export const formatAggregationAxisValueWithShareOfTotal = (
    trendsFilter: TrendsFilter | null | undefined | Partial<TrendsFilterType>,
    value: number | string,
    total: number,
    currency?: CurrencyCode
): string => {
    const formatted = formatAggregationAxisValue(trendsFilter, value, currency)
    const aggregationAxisFormat =
        (trendsFilter as TrendsFilter)?.aggregationAxisFormat ??
        (trendsFilter as Partial<TrendsFilterType>)?.aggregation_axis_format
    if (aggregationAxisFormat === 'percentage' || aggregationAxisFormat === 'percentage_scaled') {
        return formatted
    }
    if (!total) {
        return formatted
    }
    const shareOfTotal = parseFloat(((Number(value) / total) * 100).toFixed(1))
    return `${formatted} (${shareOfTotal}%)`
}

export const axisLabel = (chartDisplayType: ChartDisplayType | null | undefined): string => {
    switch (chartDisplayType) {
        case ChartDisplayType.ActionsLineGraph:
        case ChartDisplayType.ActionsLineGraphCumulative:
        case ChartDisplayType.ActionsBar:
        case ChartDisplayType.ActionsUnstackedBar:
        case ChartDisplayType.ActionsAreaGraph:
            return 'Y-axis unit'
        case ChartDisplayType.ActionsBarValue:
            return 'X-axis unit'
        default:
            return 'Unit'
    }
}
