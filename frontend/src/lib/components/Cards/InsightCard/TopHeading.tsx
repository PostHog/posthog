import { dateFilterToText } from 'lib/utils'
import { INSIGHT_TYPES_METADATA, InsightTypeMetadata, QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { containsHogQLQuery, dateRangeFor, isDataTableNode, isInsightQueryNode } from '~/queries/utils'
import { InsightModel, InsightType } from '~/types'

export function TopHeading({ insight }: { insight: InsightModel }): JSX.Element {
    const { filters, query } = insight

    let insightType: InsightTypeMetadata

    // check the query first because the backend still adds defaults to empty filters :/
    if (query?.kind) {
        if (isDataTableNode(query) && containsHogQLQuery(query)) {
            insightType = QUERY_TYPES_METADATA[query.source.kind]
        } else {
            insightType = QUERY_TYPES_METADATA[query.kind]
        }
    } else if (filters.insight) {
        insightType = INSIGHT_TYPES_METADATA[filters.insight]
    } else {
        // maintain the existing default
        insightType = INSIGHT_TYPES_METADATA[InsightType.TRENDS]
    }

    let { date_from, date_to } = filters
    if (query) {
        const queryDateRange = dateRangeFor(query)
        if (queryDateRange) {
            date_from = queryDateRange.date_from
            date_to = queryDateRange.date_to
        }
    }

    const defaultDateRange = query == undefined || isInsightQueryNode(query) ? 'Last 7 days' : null
    const dateText = dateFilterToText(date_from, date_to, defaultDateRange)
    return (
        <>
            <span title={insightType?.description}>{insightType?.name}</span>
            {dateText ? <> • {dateText}</> : null}
        </>
    )
}
