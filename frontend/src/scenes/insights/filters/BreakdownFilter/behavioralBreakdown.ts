import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'

import { InsightQueryNode, TrendsQuery, TrendsQuerySeriesNode } from '~/queries/schema/schema-general'
import { hasBreakdownFilter, isActionsNode, isEventsNode, isTrendsQuery } from '~/queries/utils'
import { BehavioralPropertyFilter } from '~/types'

export function canAddBehavioralBreakdown(
    query: InsightQueryNode | null | undefined,
    featureEnabled: boolean
): query is TrendsQuery {
    if (!featureEnabled || !isTrendsQuery(query)) {
        return false
    }

    const { breakdownFilter, series, trendsFilter } = query
    return (
        series.length === 1 &&
        (isEventsNode(series[0]) || isActionsNode(series[0])) &&
        !hasBreakdownFilter(breakdownFilter) &&
        !trendsFilter?.formula &&
        !trendsFilter?.formulas?.length &&
        !trendsFilter?.formulaNodes?.length &&
        (!trendsFilter?.display || !SINGLE_SERIES_DISPLAY_TYPES.includes(trendsFilter.display))
    )
}

export function createBehavioralBreakdownSeries(
    series: TrendsQuerySeriesNode,
    filter: BehavioralPropertyFilter
): TrendsQuerySeriesNode[] {
    const properties = [...(series.properties ?? []), filter]

    return [
        { ...series, custom_name: 'Performed', properties },
        {
            ...series,
            custom_name: 'Did not perform',
            properties: [...(series.properties ?? []), { ...filter, negation: true }],
        },
    ]
}
