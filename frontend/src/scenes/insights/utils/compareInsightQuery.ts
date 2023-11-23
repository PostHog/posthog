import { objectCleanWithEmpty, objectsEqual } from 'lib/utils'

import { InsightQueryNode } from '~/queries/schema'
import {
    filterForQuery,
    filterKeyForQuery,
    isEventsNode,
    isInsightQueryWithDisplay,
    isInsightQueryWithSeries,
} from '~/queries/utils'
import { ChartDisplayType } from '~/types'

const groupedChartDisplayTypes: Record<ChartDisplayType, ChartDisplayType> = {
    // time series
    [ChartDisplayType.ActionsLineGraph]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.ActionsBar]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.ActionsAreaGraph]: ChartDisplayType.ActionsLineGraph,

    // cumulative time series
    [ChartDisplayType.ActionsLineGraphCumulative]: ChartDisplayType.ActionsLineGraphCumulative,

    // total value
    [ChartDisplayType.BoldNumber]: ChartDisplayType.ActionsBarValue,
    [ChartDisplayType.ActionsBarValue]: ChartDisplayType.ActionsBarValue,
    [ChartDisplayType.ActionsPie]: ChartDisplayType.ActionsBarValue,
    [ChartDisplayType.ActionsTable]: ChartDisplayType.ActionsBarValue,
    [ChartDisplayType.WorldMap]: ChartDisplayType.ActionsBarValue,
}

/** clean insight queries so that we can check for semantic equality with a deep equality check */
const cleanInsightQuery = (query: InsightQueryNode, ignoreVisualizationOnlyChanges: boolean): InsightQueryNode => {
    const dupQuery = JSON.parse(JSON.stringify(query))

    // remove undefined values, empty arrays and empty objects
    const cleanedQuery = objectCleanWithEmpty(dupQuery) as InsightQueryNode

    if (isInsightQueryWithSeries(cleanedQuery)) {
        cleanedQuery.series?.forEach((e) => {
            // event math `total` is the default
            if (isEventsNode(e) && e.math === 'total') {
                delete e.math
            }
        })
    }

    if (ignoreVisualizationOnlyChanges) {
        const insightFilter = filterForQuery(cleanedQuery)
        const insightFilterKey = filterKeyForQuery(cleanedQuery)
        cleanedQuery[insightFilterKey] = {
            ...insightFilter,
            show_legend: undefined,
            show_percent_stack_view: undefined,
            show_values_on_series: undefined,
            aggregation_axis_format: undefined,
            aggregation_axis_prefix: undefined,
            aggregation_axis_postfix: undefined,
            layout: undefined,
            toggledLifecycles: undefined,
        }

        if (isInsightQueryWithDisplay(cleanedQuery)) {
            cleanedQuery[insightFilterKey].display =
                groupedChartDisplayTypes[cleanedQuery[insightFilterKey].display || ChartDisplayType.ActionsLineGraph]
        }
    }

    return cleanedQuery
}

/** compares two insight queries for semantical equality */
export function compareInsightQuery(
    a: InsightQueryNode,
    b: InsightQueryNode,
    /** Ignores changes that only alter frontend-side display and not how the
     * underlying data is generated. This is useful to prevent unnecessary
     * requests to the backend. */
    ignoreVisualizationOnlyChanges: boolean
): boolean {
    return objectsEqual(
        cleanInsightQuery(a, ignoreVisualizationOnlyChanges),
        cleanInsightQuery(b, ignoreVisualizationOnlyChanges)
    )
}
