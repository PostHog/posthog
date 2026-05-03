import { YFormatterConfig } from 'lib/hog-charts/charts/TimeSeriesLineChart/utils/y-formatters'

import { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

/** Map a `TrendsFilter` (+ percent-stack flag and project currency) to the generic
 *  `YFormatterConfig` consumed by `buildYTickFormatter` in `lib/hog-charts`. */
export function trendsFilterToYFormatterConfig(
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
