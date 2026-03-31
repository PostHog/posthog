import { NON_VALUES_ON_SERIES_DISPLAY_TYPES } from 'lib/constants'

import { isFunnelsQuery, isInsightVizNode, isLifecycleQuery, isStickinessQuery, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType, FunnelVizType, QueryBasedInsightModel } from '~/types'

export type DisplayLabelsToggleMode = 'pie_labels' | 'series_values'

export function canToggleDisplayLabelsInInsightQuery(query: QueryBasedInsightModel['query']): boolean {
    if (!isInsightVizNode(query)) {
        return false
    }

    if (isTrendsQuery(query.source)) {
        const display = query.source.trendsFilter?.display || ChartDisplayType.ActionsLineGraph
        return display === ChartDisplayType.ActionsPie || !NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(display)
    }

    if (isStickinessQuery(query.source)) {
        const display = query.source.stickinessFilter?.display || ChartDisplayType.ActionsLineGraph
        return !NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(display)
    }

    if (isFunnelsQuery(query.source)) {
        return query.source.funnelsFilter?.funnelVizType === FunnelVizType.Trends
    }

    if (isLifecycleQuery(query.source)) {
        return true
    }

    return false
}

export function isDisplayLabelsEnabledInInsightQuery(query: QueryBasedInsightModel['query']): boolean {
    if (!canToggleDisplayLabelsInInsightQuery(query) || !isInsightVizNode(query)) {
        return false
    }

    if (isTrendsQuery(query.source)) {
        const display = query.source.trendsFilter?.display || ChartDisplayType.ActionsLineGraph
        return display === ChartDisplayType.ActionsPie
            ? !!query.source.trendsFilter?.showLabelsOnSeries
            : !!query.source.trendsFilter?.showValuesOnSeries
    }

    if (isStickinessQuery(query.source)) {
        return !!query.source.stickinessFilter?.showValuesOnSeries
    }

    if (isFunnelsQuery(query.source)) {
        return !!query.source.funnelsFilter?.showValuesOnSeries
    }

    return isLifecycleQuery(query.source) && !!query.source.lifecycleFilter?.showValuesOnSeries
}

export function getDisplayLabelsToggleMode(query: QueryBasedInsightModel['query']): DisplayLabelsToggleMode | null {
    if (!isInsightVizNode(query)) {
        return null
    }

    if (isTrendsQuery(query.source)) {
        const display = query.source.trendsFilter?.display || ChartDisplayType.ActionsLineGraph
        return display === ChartDisplayType.ActionsPie ? 'pie_labels' : 'series_values'
    }

    if (isStickinessQuery(query.source) || isFunnelsQuery(query.source) || isLifecycleQuery(query.source)) {
        return 'series_values'
    }

    return null
}

export function getDisplayLabelsToggleText(query: QueryBasedInsightModel['query']): string {
    const displayLabelsShown = isDisplayLabelsEnabledInInsightQuery(query)
    const displayLabelsToggleMode = getDisplayLabelsToggleMode(query)

    if (displayLabelsToggleMode === 'pie_labels') {
        return displayLabelsShown ? 'Hide labels on series' : 'Show labels on series'
    }

    return displayLabelsShown ? 'Hide values on series' : 'Show values on series'
}

export function toggleDisplayLabelsInInsightQuery(
    query: QueryBasedInsightModel['query']
): QueryBasedInsightModel['query'] {
    if (!isInsightVizNode(query)) {
        return query
    }

    const queryWithSource = query as any
    const source = queryWithSource.source

    if (isTrendsQuery(source)) {
        const display = source.trendsFilter?.display || ChartDisplayType.ActionsLineGraph
        if (display === ChartDisplayType.ActionsPie) {
            return {
                ...queryWithSource,
                source: {
                    ...source,
                    trendsFilter: {
                        ...source.trendsFilter,
                        showLabelsOnSeries: !source.trendsFilter?.showLabelsOnSeries,
                    },
                },
            } as QueryBasedInsightModel['query']
        }

        if (NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(display)) {
            return query
        }

        return {
            ...queryWithSource,
            source: {
                ...source,
                trendsFilter: {
                    ...source.trendsFilter,
                    showValuesOnSeries: !source.trendsFilter?.showValuesOnSeries,
                },
            },
        } as QueryBasedInsightModel['query']
    }

    if (isStickinessQuery(source)) {
        const display = source.stickinessFilter?.display || ChartDisplayType.ActionsLineGraph
        if (NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(display)) {
            return query
        }

        return {
            ...queryWithSource,
            source: {
                ...source,
                stickinessFilter: {
                    ...source.stickinessFilter,
                    showValuesOnSeries: !source.stickinessFilter?.showValuesOnSeries,
                },
            },
        } as QueryBasedInsightModel['query']
    }

    if (isFunnelsQuery(source)) {
        return {
            ...queryWithSource,
            source: {
                ...source,
                funnelsFilter: {
                    ...source.funnelsFilter,
                    showValuesOnSeries: !source.funnelsFilter?.showValuesOnSeries,
                },
            },
        } as QueryBasedInsightModel['query']
    }

    if (isLifecycleQuery(source)) {
        return {
            ...queryWithSource,
            source: {
                ...source,
                lifecycleFilter: {
                    ...source.lifecycleFilter,
                    showValuesOnSeries: !source.lifecycleFilter?.showValuesOnSeries,
                },
            },
        } as QueryBasedInsightModel['query']
    }

    return query
}
