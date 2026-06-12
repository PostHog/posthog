import { InsightVizNode } from '@posthog/query-frontend/schema/schema-general'
import {
    getShowLegend,
    hasBreakdownFilter,
    isFunnelsQuery,
    isInsightVizNode,
    isLifecycleQuery,
    isStickinessQuery,
    isTrendsQuery,
} from '@posthog/query-frontend/utils'

import { DISPLAY_TYPES_WITHOUT_LEGEND } from 'lib/components/InsightLegend/utils'

import { FunnelVizType, QueryBasedInsightModel } from '~/types'

// Eligibility matches insightVizDataLogic `hasLegend` (trends / stickiness / lifecycle, excluding DISPLAY_TYPES_WITHOUT_LEGEND).

export function canToggleLegendInInsightQuery(
    query: QueryBasedInsightModel['query'],
    hogChartsFunnelEnabled: boolean = false
): boolean {
    if (!isInsightVizNode(query)) {
        return false
    }

    const source = query.source

    if (isFunnelsQuery(source)) {
        return (
            hogChartsFunnelEnabled &&
            source.funnelsFilter?.funnelVizType === FunnelVizType.Trends &&
            hasBreakdownFilter(source.breakdownFilter)
        )
    }

    const isTrends = isTrendsQuery(source)
    const isStickiness = isStickinessQuery(source)
    const isLifecycle = isLifecycleQuery(source)
    if (!isTrends && !isStickiness && !isLifecycle) {
        return false
    }

    const display = isTrends
        ? source.trendsFilter?.display
        : isStickiness
          ? source.stickinessFilter?.display
          : undefined

    return !(display && DISPLAY_TYPES_WITHOUT_LEGEND.includes(display))
}

export function isLegendEnabledInInsightQuery(
    query: QueryBasedInsightModel['query'],
    hogChartsFunnelEnabled: boolean = false
): boolean {
    if (!canToggleLegendInInsightQuery(query, hogChartsFunnelEnabled) || !isInsightVizNode(query)) {
        return false
    }

    return !!getShowLegend(query.source)
}

export function getLegendToggleText(
    query: QueryBasedInsightModel['query'],
    hogChartsFunnelEnabled: boolean = false
): string {
    return isLegendEnabledInInsightQuery(query, hogChartsFunnelEnabled) ? 'Hide legend' : 'Show legend'
}

export function toggleLegendInInsightQuery(query: QueryBasedInsightModel['query']): QueryBasedInsightModel['query'] {
    if (!isInsightVizNode(query)) {
        return query
    }

    const viz: InsightVizNode = query
    const source = viz.source
    const nextShowLegend = !getShowLegend(source)

    if (isTrendsQuery(source)) {
        return {
            ...viz,
            source: {
                ...source,
                trendsFilter: {
                    ...source.trendsFilter,
                    showLegend: nextShowLegend,
                },
            },
        } as QueryBasedInsightModel['query']
    }

    if (isStickinessQuery(source)) {
        return {
            ...viz,
            source: {
                ...source,
                stickinessFilter: {
                    ...source.stickinessFilter,
                    showLegend: nextShowLegend,
                },
            },
        } as QueryBasedInsightModel['query']
    }

    if (isLifecycleQuery(source)) {
        return {
            ...viz,
            source: {
                ...source,
                lifecycleFilter: {
                    ...source.lifecycleFilter,
                    showLegend: nextShowLegend,
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
                    showLegend: nextShowLegend,
                },
            },
        } as QueryBasedInsightModel['query']
    }

    return query
}
