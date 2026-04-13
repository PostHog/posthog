import { objectCleanWithEmpty, objectsEqual, removeUndefinedAndNull } from 'lib/utils'
import { isValidRE2 } from 'lib/utils/regexp'
import { isFunnelWithEnoughSteps, isFunnelWithIncompleteDataWarehouseStep } from 'scenes/funnels/funnelUtils'

import { Variable } from '~/queries/nodes/DataVisualization/types'
import { DataNode, HogQLVariable, InsightQueryNode, Node } from '~/queries/schema/schema-general'
import {
    filterForQuery,
    getMathTypeWarning,
    isEventsNode,
    isFunnelsQuery,
    isHogQLQuery,
    isLifecycleQuery,
    isInsightQueryNode,
    isInsightQueryWithDisplay,
    isInsightQueryWithSeries,
    isInsightVizNode,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
    isWebAnalyticsInsightQuery,
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

export const filterVariablesReferencedInQuery = <T extends { code_name: string }>(
    query: string | null | undefined,
    variables: T[]
): T[] => {
    const queryCodeNames = new Set(getVariablesFromQuery(query ?? ''))

    return variables.filter((variable) => queryCodeNames.has(variable.code_name))
}

export const syncSelectedVariablesToQuery = (
    query: string | null | undefined,
    variables: Pick<Variable, 'id' | 'code_name'>[],
    selectedVariables: HogQLVariable[]
): HogQLVariable[] => {
    const queryCodeNames = Array.from(new Set(getVariablesFromQuery(query ?? '')))
    const queryCodeNamesSet = new Set(queryCodeNames)
    const variablesByCodeName = new Map(variables.map((variable) => [variable.code_name, variable]))

    const syncedVariables = selectedVariables.filter((variable) => queryCodeNamesSet.has(variable.code_name))
    const selectedVariableIds = new Set(syncedVariables.map((variable) => variable.variableId))

    queryCodeNames.forEach((codeName) => {
        const variable = variablesByCodeName.get(codeName)

        if (!variable || selectedVariableIds.has(variable.id)) {
            return
        }

        syncedVariables.push({
            variableId: variable.id,
            code_name: variable.code_name,
        })
    })

    return syncedVariables
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

export const hasInvalidRegexFilter = (obj: unknown): boolean => {
    if (Array.isArray(obj)) {
        return obj.some(hasInvalidRegexFilter)
    }

    if (obj !== null && typeof obj === 'object') {
        const record = obj as Record<string, unknown>
        if (
            (record.operator === 'regex' || record.operator === 'not_regex') &&
            typeof record.value === 'string' &&
            !isValidRE2(record.value)
        ) {
            return true
        }

        return Object.values(record).some(hasInvalidRegexFilter)
    }

    return false
}

export const validateQuery = (q: DataNode): boolean => {
    if (isFunnelsQuery(q)) {
        return isFunnelWithEnoughSteps(q.series) && !isFunnelWithIncompleteDataWarehouseStep(q.series)
    }

    if (isTrendsQuery(q) && q.trendsFilter?.display === ChartDisplayType.BoxPlot) {
        return q.series?.length > 0 && q.series.every((s) => !!s?.math_property)
    }
    if (hasInvalidRegexFilter(q)) {
        return false
    }
    return true
}

// keep in sync with posthog/schema_helpers.py `grouped_chart_display_types` method
const groupedChartDisplayTypes: Record<ChartDisplayType, ChartDisplayType> = {
    [ChartDisplayType.Auto]: ChartDisplayType.Auto,

    // time series
    [ChartDisplayType.ActionsLineGraph]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.ActionsAreaGraph]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.ActionsBar]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.ActionsUnstackedBar]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.ActionsStackedBar]: ChartDisplayType.ActionsLineGraph,
    [ChartDisplayType.TwoDimensionalHeatmap]: ChartDisplayType.ActionsLineGraph,

    // cumulative time series
    [ChartDisplayType.ActionsLineGraphCumulative]: ChartDisplayType.ActionsLineGraphCumulative,

    // total value
    [ChartDisplayType.BoldNumber]: ChartDisplayType.ActionsBarValue,
    [ChartDisplayType.ActionsBarValue]: ChartDisplayType.ActionsBarValue,
    [ChartDisplayType.ActionsPie]: ChartDisplayType.ActionsBarValue,
    [ChartDisplayType.ActionsTable]: ChartDisplayType.ActionsBarValue,

    // separate: different breakdown limit (250)
    [ChartDisplayType.WorldMap]: ChartDisplayType.WorldMap,

    // separate runner
    [ChartDisplayType.CalendarHeatmap]: ChartDisplayType.CalendarHeatmap,

    // separate runner
    [ChartDisplayType.BoxPlot]: ChartDisplayType.BoxPlot,
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

    if (opts?.ignoreVisualizationOnlyChanges && !isWebAnalyticsInsightQuery(cleanedQuery)) {
        // Keep this in sync with posthog/schema_helpers.py `serialize_query` method
        const insightFilter = filterForQuery(cleanedQuery)
        const sanitizedInsightFilter = {
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
            excludeBoxPlotOutliers: undefined,
            showFullUrls: undefined,
            selectedInterval: undefined,
            funnelStepReference: undefined,
            breakdownSorting: undefined,
            dataColorTheme: undefined,
        }

        if (isTrendsQuery(cleanedQuery)) {
            cleanedQuery.trendsFilter = sanitizedInsightFilter
            if (isInsightQueryWithDisplay(cleanedQuery)) {
                cleanedQuery.trendsFilter.display =
                    groupedChartDisplayTypes[cleanedQuery.trendsFilter?.display || ChartDisplayType.ActionsLineGraph]
            }
        } else if (isFunnelsQuery(cleanedQuery)) {
            cleanedQuery.funnelsFilter = sanitizedInsightFilter
        } else if (isRetentionQuery(cleanedQuery)) {
            cleanedQuery.retentionFilter = sanitizedInsightFilter
            if (isInsightQueryWithDisplay(cleanedQuery)) {
                cleanedQuery.retentionFilter.display =
                    groupedChartDisplayTypes[cleanedQuery.retentionFilter?.display || ChartDisplayType.ActionsLineGraph]
            }
        } else if (isPathsQuery(cleanedQuery)) {
            cleanedQuery.pathsFilter = sanitizedInsightFilter
        } else if (isStickinessQuery(cleanedQuery)) {
            cleanedQuery.stickinessFilter = sanitizedInsightFilter
            if (isInsightQueryWithDisplay(cleanedQuery)) {
                cleanedQuery.stickinessFilter.display =
                    groupedChartDisplayTypes[
                        cleanedQuery.stickinessFilter?.display || ChartDisplayType.ActionsLineGraph
                    ]
            }
        } else if (isLifecycleQuery(cleanedQuery)) {
            cleanedQuery.lifecycleFilter = sanitizedInsightFilter
        }
    }

    return cleanedQuery
}
