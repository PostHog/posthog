import { ActionsNode, BreakdownFilter, EventsNode, InsightQueryNode, TrendsQuery } from '~/queries/schema'
import { ActionType, ChartDisplayType, InsightModel, IntervalType } from '~/types'
import { seriesToActionsAndEvents } from '../InsightQuery/utils/queryNodeToFilter'
import { getEventNamesForAction, isEmptyObject } from 'lib/utils'
import {
    isInsightQueryWithBreakdown,
    isInsightQueryWithSeries,
    isLifecycleQuery,
    isStickinessQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { filtersToQueryNode } from '../InsightQuery/utils/filtersToQueryNode'
import equal from 'fast-deep-equal'

export const getAllEventNames = (query: InsightQueryNode, allActions: ActionType[]): string[] => {
    const { actions, events } = seriesToActionsAndEvents((query as TrendsQuery).series || [])

    // If there's a "All events" entity, don't filter by event names.
    if (events.find((e) => e.id === null)) {
        return []
    }

    const allEvents = [
        ...events.map((e) => String(e.id)),
        ...actions.flatMap((action) => getEventNamesForAction(action.id as string | number, allActions)),
    ]

    // remove duplicates and empty events
    return Array.from(new Set(allEvents.filter((a): a is string => !!a)))
}

export const getDisplay = (query: InsightQueryNode): ChartDisplayType | undefined => {
    if (isStickinessQuery(query)) {
        return query.stickinessFilter?.display
    } else if (isTrendsQuery(query)) {
        return query.trendsFilter?.display
    } else {
        return undefined
    }
}

export const getCompare = (query: InsightQueryNode): boolean | undefined => {
    if (isStickinessQuery(query)) {
        return query.stickinessFilter?.compare
    } else if (isTrendsQuery(query)) {
        return query.trendsFilter?.compare
    } else {
        return undefined
    }
}

export const getFormula = (query: InsightQueryNode): string | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.formula
    } else {
        return undefined
    }
}

export const getSeries = (query: InsightQueryNode): (EventsNode | ActionsNode)[] | undefined => {
    if (isInsightQueryWithSeries(query)) {
        return query.series
    } else {
        return undefined
    }
}

export const getInterval = (query: InsightQueryNode): IntervalType | undefined => {
    if (isInsightQueryWithSeries(query)) {
        return query.interval
    } else {
        return undefined
    }
}

export const getBreakdown = (query: InsightQueryNode): BreakdownFilter | undefined => {
    if (isInsightQueryWithBreakdown(query)) {
        return query.breakdown
    } else {
        return undefined
    }
}

export const getShowLegend = (query: InsightQueryNode): boolean | undefined => {
    if (isStickinessQuery(query)) {
        return query.stickinessFilter?.show_legend
    } else if (isTrendsQuery(query)) {
        return query.trendsFilter?.show_legend
    } else {
        return undefined
    }
}

export const getShowValueOnSeries = (query: InsightQueryNode): boolean | undefined => {
    if (isLifecycleQuery(query)) {
        return query.lifecycleFilter?.show_values_on_series
    } else if (isStickinessQuery(query)) {
        return query.stickinessFilter?.show_values_on_series
    } else if (isTrendsQuery(query)) {
        return query.trendsFilter?.show_values_on_series
    } else {
        return undefined
    }
}

export const getShowLabelsOnSeries = (query: InsightQueryNode): boolean | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.show_labels_on_series
    } else {
        return undefined
    }
}

export const getShowPercentStackView = (query: InsightQueryNode): boolean | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.show_percent_stack_view
    } else {
        return undefined
    }
}

export const getCachedResults = (
    cachedInsight: Partial<InsightModel> | undefined | null,
    query: InsightQueryNode
): Partial<InsightModel> | undefined => {
    if (!cachedInsight || cachedInsight.filters === undefined || isEmptyObject(cachedInsight.filters)) {
        return undefined
    }

    // only set the cached result when the filters match the currently set ones
    const cachedQueryNode = filtersToQueryNode(cachedInsight.filters)
    if (!equal(cachedQueryNode, query)) {
        return undefined
    }

    return cachedInsight
}
