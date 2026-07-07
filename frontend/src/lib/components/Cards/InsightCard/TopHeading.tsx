import { CardTopHeadingRow } from 'lib/components/Cards/CardTopHeadingRow'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { alignResolvedDateRangeToInterval, formatResolvedDateRange } from 'lib/utils/datetime'
import { InsightTypeMetadata, QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { Node, NodeKind, ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import {
    containsHogQLQuery,
    dateRangeFor,
    getInterval,
    isDataTableNode,
    isInsightQueryNode,
    isInsightVizNode,
} from '~/queries/utils'

import { InsightFreshness } from './InsightFreshness'
import { TileOverridesWarning } from './TileOverridesWarning'

function getInsightType(query: Node | null): InsightTypeMetadata {
    if (query?.kind) {
        if ((isDataTableNode(query) && containsHogQLQuery(query)) || isInsightVizNode(query)) {
            return QUERY_TYPES_METADATA[query.source.kind]
        }
        return QUERY_TYPES_METADATA[query.kind]
    }
    return QUERY_TYPES_METADATA[NodeKind.TrendsQuery]
}

export function TopHeading({
    query,
    lastRefresh,
    hasTileOverrides,
    resolvedDateRange,
    showInsightType = true,
    showDate = true,
    dateFromOverride,
    dateToOverride,
}: {
    query: Node | null
    lastRefresh?: string | null
    hasTileOverrides?: boolean | null
    resolvedDateRange?: ResolvedDateRangeResponse | null
    showInsightType?: boolean
    showDate?: boolean
    dateFromOverride?: string | null
    dateToOverride?: string | null
}): JSX.Element {
    const insightType = getInsightType(query)

    let date_from, date_to
    if (query) {
        const queryDateRange = dateRangeFor(query)
        if (queryDateRange) {
            date_from = queryDateRange.date_from
            date_to = queryDateRange.date_to
        }
    }
    if (dateFromOverride != null) {
        date_from = dateFromOverride
    }
    if (dateToOverride != null) {
        date_to = dateToOverride
    }

    let dateText: string | null = null
    if (insightType?.name !== 'Retention') {
        const defaultDateRange =
            query == undefined || isInsightQueryNode(query) || isInsightVizNode(query) ? 'Last 7 days' : null
        dateText = dateFilterToText(date_from, date_to, defaultDateRange)
    }
    const dateLabel = showDate ? dateText : null

    const insightQueryNode = isInsightVizNode(query) ? query.source : isInsightQueryNode(query) ? query : null
    const interval = insightQueryNode ? getInterval(insightQueryNode) : null
    const resolvedDateTooltip = formatResolvedDateRange(alignResolvedDateRangeToInterval(resolvedDateRange, interval))

    return (
        <CardTopHeadingRow
            typeLabel={insightType?.name}
            typeTitle={insightType?.description}
            showTypeLabel={showInsightType}
            dateText={dateLabel}
            dateTooltip={resolvedDateTooltip}
        >
            {/* Freshness clock lives in the date row — without a date it would hold the row open on its own. */}
            {dateLabel && lastRefresh ? <InsightFreshness lastRefresh={lastRefresh} /> : null}
            {hasTileOverrides ? <TileOverridesWarning /> : null}
        </CardTopHeadingRow>
    )
}
