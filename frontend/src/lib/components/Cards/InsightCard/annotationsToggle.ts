import { InsightVizNode } from '@posthog/query-frontend/schema/schema-general'
import { getShowAnnotations, isFunnelsQuery, isInsightVizNode, isTrendsQuery } from '@posthog/query-frontend/utils'

import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'

import { ChartDisplayType, FunnelVizType, QueryBasedInsightModel } from '~/types'

// Annotations only render for trends time-series charts and funnels with the historical-trends viz type.
export function canToggleAnnotationsInInsightQuery(query: QueryBasedInsightModel['query']): boolean {
    if (!isInsightVizNode(query)) {
        return false
    }

    const source = query.source
    if (isTrendsQuery(source)) {
        const display = source.trendsFilter?.display || ChartDisplayType.ActionsLineGraph
        return !NON_TIME_SERIES_DISPLAY_TYPES.includes(display)
    }

    if (isFunnelsQuery(source)) {
        return source.funnelsFilter?.funnelVizType === FunnelVizType.Trends
    }

    return false
}

export function isAnnotationsEnabledInInsightQuery(query: QueryBasedInsightModel['query']): boolean {
    if (!canToggleAnnotationsInInsightQuery(query) || !isInsightVizNode(query)) {
        return false
    }
    // Default true — treat undefined as enabled.
    return getShowAnnotations(query.source) !== false
}

export function getAnnotationsToggleText(query: QueryBasedInsightModel['query']): string {
    return isAnnotationsEnabledInInsightQuery(query) ? 'Hide annotations' : 'Show annotations'
}

export function toggleAnnotationsInInsightQuery(
    query: QueryBasedInsightModel['query']
): QueryBasedInsightModel['query'] {
    if (!isInsightVizNode(query)) {
        return query
    }

    const viz: InsightVizNode = query
    const source = viz.source
    const nextShowAnnotations = getShowAnnotations(source) === false

    if (isTrendsQuery(source)) {
        return {
            ...viz,
            source: {
                ...source,
                trendsFilter: {
                    ...source.trendsFilter,
                    showAnnotations: nextShowAnnotations,
                },
            },
        } as QueryBasedInsightModel['query']
    }

    if (isFunnelsQuery(source)) {
        return {
            ...viz,
            source: {
                ...source,
                funnelsFilter: {
                    ...source.funnelsFilter,
                    showAnnotations: nextShowAnnotations,
                },
            },
        } as QueryBasedInsightModel['query']
    }

    return query
}
