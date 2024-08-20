import { objectCleanWithEmpty, objectsEqual } from 'lib/utils'

import { DataNode, InsightQueryNode, Node } from '~/queries/schema'
import {
    filterForQuery,
    filterKeyForQuery,
    isEventsNode,
    isFunnelsQuery,
    isInsightQueryNode,
    isInsightQueryWithDisplay,
    isInsightQueryWithSeries,
    isInsightVizNode,
} from '~/queries/utils'
import { ChartDisplayType } from '~/types'

type CompareQueryOpts = { ignoreVisualizationOnlyChanges: boolean }

export const compareQuery = (a: Node, b: Node, opts?: CompareQueryOpts): boolean => {
    if (isInsightVizNode(a) && isInsightVizNode(b)) {
        const { source: sourceA, ...restA } = a
        const { source: sourceB, ...restB } = b
        return (
            objectsEqual(objectCleanWithEmpty(restA), objectCleanWithEmpty(restB)) &&
            compareDataNodeQuery(sourceA, sourceB, opts)
        )
    } else if (isInsightQueryNode(a) && isInsightQueryNode(b)) {
        return compareDataNodeQuery(a, b, opts)
    }

    return objectsEqual(objectCleanWithEmpty(a as any), objectCleanWithEmpty(b as any))
}

/** Compares two queries for semantic equality to prevent double-fetching of data. */
export const compareDataNodeQuery = (a: Node, b: Node, opts?: CompareQueryOpts): boolean => {
    if (isInsightQueryNode(a) && isInsightQueryNode(b)) {
        return objectsEqual(cleanInsightQuery(a, opts), cleanInsightQuery(b, opts))
    }

    return objectsEqual(objectCleanWithEmpty(a as any), objectCleanWithEmpty(b as any))
}

/** Tests wether a query is valid to prevent unnecessary requests.  */
export const validateQuery = (q: DataNode): boolean => {
    if (isFunnelsQuery(q)) {
        // funnels require at least two steps
        return q.series.length >= 2
    }
    return true
}

const groupedChartDisplayTypes: Record<ChartDisplayType, ChartDisplayType> = {
    // time series
    [ChartDisplayType.ActionsLineGraph]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.ActionsBar]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.ActionsAreaGraph]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.ActionsStackedBar]: ChartDisplayType.ActionsLineGraph,

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
const cleanInsightQuery = (query: InsightQueryNode, opts?: CompareQueryOpts): InsightQueryNode => {
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

    if (opts?.ignoreVisualizationOnlyChanges) {
        // Keep this in sync with the backend side clean_insight_queries method
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
            showMean: undefined,
            cumulative: undefined,
            yAxisScaleType: undefined,
            hiddenLegendIndexes: undefined,
            hiddenLegendBreakdowns: undefined,
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
