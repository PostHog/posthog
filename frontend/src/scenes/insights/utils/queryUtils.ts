import { objectCleanWithEmpty, objectsEqual, removeUndefinedAndNull } from 'lib/utils'

import { DataNode, InsightQueryNode, Node } from '~/queries/schema/schema-general'
import {
    filterForQuery,
    filterKeyForQuery,
    getMathTypeWarning,
    isEventsNode,
    isFunnelsQuery,
    isHogQLQuery,
    isInsightQueryNode,
    isInsightQueryWithDisplay,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isTrendsQuery,
} from '~/queries/utils'
import { BaseMathType, ChartDisplayType } from '~/types'

type CompareQueryOpts = { ignoreVisualizationOnlyChanges: boolean }

export const getVariablesFromQuery = (query: string): string[] => {
    const re = /\{variables\.([a-z0-9_]+)\}/gm
    const results: string[] = []

    for (;;) {
        const reResult = re.exec(query)
        if (!reResult) {
            break
        }

        if (reResult[1]) {
            results.push(reResult[1])
        }
    }

    return results
}

export const compareQuery = (a: Node, b: Node, opts?: CompareQueryOpts): boolean => {
    if (isInsightVizNode(a) && isInsightVizNode(b)) {
        const { source: sourceA, ...restA } = a
        const { source: sourceB, ...restB } = b
        return (
            objectsEqual(
                objectCleanWithEmpty(removeUndefinedAndNull(restA)),
                objectCleanWithEmpty(removeUndefinedAndNull(restB))
            ) && compareDataNodeQuery(sourceA, sourceB, opts)
        )
    } else if (isInsightQueryNode(a) && isInsightQueryNode(b)) {
        return compareDataNodeQuery(removeUndefinedAndNull(a), removeUndefinedAndNull(b), opts)
    }

    return objectsEqual(
        objectCleanWithEmpty(removeUndefinedAndNull(a as any)),
        objectCleanWithEmpty(removeUndefinedAndNull(b as any))
    )
}

export const haveVariablesOrFiltersChanged = (a: Node, b: Node): boolean => {
    if (!isHogQLQuery(a) || !isHogQLQuery(b)) {
        return false
    }

    if ((a.variables && !b.variables) || (!a.variables && b.variables)) {
        return true
    }

    if (a.variables && b.variables) {
        if (!objectsEqual(a.variables, b.variables)) {
            return true
        }
    }

    if (a.filters && b.filters) {
        if (!objectsEqual(a.filters, b.filters)) {
            return true
        }
    }

    return false
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
    [ChartDisplayType.ActionsUnstackedBar]: ChartDisplayType.ActionsLineGraph,
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
    [ChartDisplayType.CalendarHeatmap]: ChartDisplayType.ActionsBarValue,
}

/** clean insight queries so that we can check for semantic equality with a deep equality check */
export const cleanInsightQuery = (query: InsightQueryNode, opts?: CompareQueryOpts): InsightQueryNode => {
    const dupQuery = JSON.parse(JSON.stringify(query))

    // remove undefined values, empty arrays and empty objects
    const cleanedQuery = objectCleanWithEmpty(dupQuery) as InsightQueryNode

    if (isInsightQueryWithSeries(cleanedQuery)) {
        cleanedQuery.series?.forEach((series) => {
            // event math `total` is the default
            if (isEventsNode(series) && series.math === 'total') {
                delete series.math
            } else if (isTrendsQuery(cleanedQuery) && series.math && getMathTypeWarning(series.math, query, false)) {
                series.math = BaseMathType.UniqueUsers
            }
        })
    }

    if (opts?.ignoreVisualizationOnlyChanges) {
        // Keep this in sync with posthog/schema_helpers.py `serialize_query` method
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
            meanRetentionCalculation: undefined,
            yAxisScaleType: undefined,
            hiddenLegendIndexes: undefined,
            hiddenLegendBreakdowns: undefined,
            resultCustomizations: undefined,
            resultCustomizationBy: undefined,
            goalLines: undefined,
            dashboardDisplay: undefined,
            showConfidenceIntervals: undefined,
            confidenceLevel: undefined,
            showTrendLines: undefined,
            showMovingAverage: undefined,
            movingAverageIntervals: undefined,
            stacked: undefined,
            detailedResultsAggregationType: undefined,
            showFullUrls: undefined,
            selectedInterval: undefined,
        }

        cleanedQuery.dataColorTheme = undefined

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
