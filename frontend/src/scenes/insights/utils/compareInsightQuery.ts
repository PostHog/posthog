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
            showLegend: undefined,
            showPercentStackView: undefined,
            showValuesOnSeries: undefined,
            aggregationAxisFormat: undefined,
            aggregationAxisPrefix: undefined,
            aggregationAxisPostfix: undefined,
            decimalPlaces: undefined,
            layout: undefined,
            toggledLifecycles: undefined,
            showLabelsOnSeries: undefined,
        }

        if (isInsightQueryWithSeries(cleanedQuery)) {
            cleanedQuery.series = cleanedQuery.series.map((entity) => {
                const { custom_name, ...cleanedEntity } = entity
                return cleanedEntity
            })
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
