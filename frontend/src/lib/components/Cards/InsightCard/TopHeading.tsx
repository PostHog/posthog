import { dateFilterToText } from 'lib/utils'
import { InsightTypeMetadata, QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { Node, NodeKind } from '~/queries/schema/schema-general'
import {
    containsHogQLQuery,
    dateRangeFor,
    isDataTableNode,
    isInsightQueryNode,
    isInsightVizNode,
} from '~/queries/utils'

import { InsightFreshness } from './InsightFreshness'
import { TileOverridesWarning } from './TileOverridesWarning'

export function TopHeading({
    query,
    lastRefresh,
    hasTileOverrides,
}: {
    query: Node | null
    lastRefresh?: string | null
    hasTileOverrides?: boolean | null
}): JSX.Element {
    let insightType: InsightTypeMetadata

    if (query?.kind) {
        if ((isDataTableNode(query) && containsHogQLQuery(query)) || isInsightVizNode(query)) {
            insightType = QUERY_TYPES_METADATA[query.source.kind]
        } else {
            insightType = QUERY_TYPES_METADATA[query.kind]
        }
    } else {
        // maintain the existing default
        insightType = QUERY_TYPES_METADATA[NodeKind.TrendsQuery]
    }

    let date_from, date_to
    if (query) {
        const queryDateRange = dateRangeFor(query)
        if (queryDateRange) {
            date_from = queryDateRange.date_from
            date_to = queryDateRange.date_to
        }
    }

    let dateText: string | null = null
    if (insightType?.name !== 'Retention') {
        const defaultDateRange =
            query == undefined || isInsightQueryNode(query) || isInsightVizNode(query) ? 'Last 7 days' : null
        dateText = dateFilterToText(date_from, date_to, defaultDateRange)
    }
    return (
        <div className="flex items-center gap-1">
            <span title={insightType?.description}>{insightType?.name}</span>
            {dateText ? (
                <>
                    {' '}
                    • <span className="whitespace-nowrap">{dateText}</span>
                </>
            ) : null}
            {lastRefresh ? <InsightFreshness lastRefresh={lastRefresh} /> : null}
            {hasTileOverrides ? <TileOverridesWarning /> : null}
        </div>
    )
}
