import { buildYTickFormatter, YFormatterConfig } from 'lib/hog-charts/charts/TimeSeriesLineChart/utils/y-formatters'

import { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

function trendsFilterToFormatterConfig(
    trendsFilter: TrendsFilter | null | undefined,
    isPercentStackView: boolean,
    baseCurrency?: CurrencyCode
): YFormatterConfig {
    if (isPercentStackView) {
        return { format: 'percentage' }
    }
    return {
        format: trendsFilter?.aggregationAxisFormat ?? 'numeric',
        prefix: trendsFilter?.aggregationAxisPrefix,
        suffix: trendsFilter?.aggregationAxisPostfix,
        decimalPlaces: trendsFilter?.decimalPlaces,
        minDecimalPlaces: trendsFilter?.minDecimalPlaces,
        currency: baseCurrency,
    }
}

/** Build the y-axis tick formatter for the trends chart from the same inputs the
 *  legacy chart.js path consumes (`trendsFilter` + percent-stack flag + project currency).
 *  Delegates to the product-free `buildYTickFormatter` in `lib/hog-charts`. */
export function buildTrendsYTickFormatter(
    trendsFilter: TrendsFilter | null | undefined,
    isPercentStackView: boolean,
    baseCurrency?: CurrencyCode
): (value: number) => string {
    return buildYTickFormatter(trendsFilterToFormatterConfig(trendsFilter, isPercentStackView, baseCurrency))
}
