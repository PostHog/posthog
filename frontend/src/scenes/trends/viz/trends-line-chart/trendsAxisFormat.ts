import { formatPercentStackAxisValue } from 'scenes/insights/aggregationAxisFormat'

import { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

/** Build the y-axis tick formatter for the trends chart from the same inputs the
 *  legacy chart.js path consumes (`trendsFilter` + percent-stack flag + project currency).
 *  `formatPercentStackAxisValue` honors `aggregationAxisFormat`, `aggregationAxisPrefix`,
 *  and `aggregationAxisPostfix`, so currency / percent / duration / numeric all flow through. */
export function buildTrendsYTickFormatter(
    trendsFilter: TrendsFilter | null | undefined,
    isPercentStackView: boolean,
    baseCurrency?: CurrencyCode
): (value: number) => string {
    return (value: number): string => formatPercentStackAxisValue(trendsFilter, value, isPercentStackView, baseCurrency)
}
