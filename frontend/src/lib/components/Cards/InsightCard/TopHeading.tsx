import clsx from 'clsx'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dateFilterToText } from 'lib/utils'
import { formatResolvedDateRange } from 'lib/utils/dateTimeUtils'
import { InsightTypeMetadata, QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { Node, NodeKind, ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import {
    containsHogQLQuery,
    dateRangeFor,
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
    colorClassName,
}: {
    query: Node | null
    lastRefresh?: string | null
    hasTileOverrides?: boolean | null
    resolvedDateRange?: ResolvedDateRangeResponse | null
    showInsightType?: boolean
    colorClassName?: string
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

    let dateText: string | null = null
    if (insightType?.name !== 'Retention') {
        const defaultDateRange =
            query == undefined || isInsightQueryNode(query) || isInsightVizNode(query) ? 'Last 7 days' : null
        dateText = dateFilterToText(date_from, date_to, defaultDateRange)
    }
    // Use accent color only for the insight type label and bullet.
    // For the date range text, prefer the standard muted text color so it has good contrast,
    // especially on dark themed headers.
    const dateClassName = clsx('whitespace-nowrap', showInsightType ? 'text-muted' : colorClassName)

    const resolvedDateTooltip = formatResolvedDateRange(resolvedDateRange)

    return (
        <div className="flex items-center gap-1">
            {showInsightType && (
                <span className={colorClassName} title={insightType?.description}>
                    {insightType?.name}
                </span>
            )}
            {dateText ? (
                <>
                    {showInsightType && <span className={colorClassName}>•</span>}
                    {resolvedDateTooltip ? (
                        <Tooltip title={resolvedDateTooltip}>
                            <span className={dateClassName}>{dateText}</span>
                        </Tooltip>
                    ) : (
                        <span className={dateClassName}>{dateText}</span>
                    )}
                </>
            ) : null}
            {lastRefresh ? <InsightFreshness lastRefresh={lastRefresh} /> : null}
            {hasTileOverrides ? <TileOverridesWarning /> : null}
        </div>
    )
}
