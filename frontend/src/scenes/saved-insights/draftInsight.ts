import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { SummaryContext, summarizeInsight } from 'scenes/insights/summarizeInsight'

import { Node, NodeKind } from '~/queries/schema/schema-general'
import { isNodeWithSource } from '~/queries/utils'
import { AccessControlLevel, InsightShortId, SavedInsightsTabs, UserBasicType, UserType } from '~/types'

import type { SavedInsightFilters, SavedInsightListItem } from './savedInsightsLogic'

/** An insight draft persisted by the insight editor in localStorage under `draft-query-${teamId}`. */
export interface DraftInsightQuery {
    query: Node<Record<string, any>>
    timestamp: number
}

/** Sentinel id for the local draft row in the saved insights table. Real insight ids are positive. */
export const DRAFT_INSIGHT_ROW_ID = -1

/** Storage can hold anything — a non-numeric timestamp would throw in draftInsightListItem and crash the list. */
export function isValidDraftInsightQuery(value: unknown): value is DraftInsightQuery {
    const draft = value as DraftInsightQuery | null
    return (
        !!draft &&
        typeof draft === 'object' &&
        !!draft.query &&
        typeof draft.query === 'object' &&
        typeof draft.query.kind === 'string' &&
        typeof draft.timestamp === 'number' &&
        Number.isFinite(draft.timestamp)
    )
}

export function isDraftInsightRow(item: SavedInsightListItem): boolean {
    return item.id === DRAFT_INSIGHT_ROW_ID
}

/** Shown (and searched) when the draft's query summarizes to nothing. */
export const DRAFT_INSIGHT_FALLBACK_NAME = 'Unsaved insight'

/** Mirrors the API's `insight` param mapping for query-based insights. */
const INSIGHT_TYPE_TO_SOURCE_KIND: Record<string, NodeKind> = {
    TRENDS: NodeKind.TrendsQuery,
    FUNNELS: NodeKind.FunnelsQuery,
    RETENTION: NodeKind.RetentionQuery,
    PATHS: NodeKind.PathsQuery,
    STICKINESS: NodeKind.StickinessQuery,
    LIFECYCLE: NodeKind.LifecycleQuery,
}

function matchesInsightTypeFilter(query: Node<Record<string, any>>, insightType: string): boolean {
    const type = insightType.toUpperCase()
    const sourceKind: NodeKind | null = isNodeWithSource(query) ? query.source.kind : null
    if (type === 'SQL') {
        return sourceKind === NodeKind.HogQLQuery
    }
    if (type === 'JSON') {
        return (
            !sourceKind ||
            (sourceKind !== NodeKind.HogQLQuery && !Object.values(INSIGHT_TYPE_TO_SOURCE_KIND).includes(sourceKind))
        )
    }
    const expectedSourceKind = INSIGHT_TYPE_TO_SOURCE_KIND[type]
    // Any other type value only matches legacy filter-based insights server-side, which a draft never is
    return !!expectedSourceKind && query.kind === NodeKind.InsightVizNode && sourceKind === expectedSourceKind
}

function timestampWithinRange(
    timestamp: dayjs.Dayjs,
    from: string | dayjs.Dayjs | undefined | null,
    to: string | dayjs.Dayjs | undefined | null
): boolean {
    const fromBound = typeof from === 'string' ? dateStringToDayJs(from) : (from ?? null)
    const toBound = typeof to === 'string' ? dateStringToDayJs(to) : (to ?? null)
    return (!fromBound || timestamp.isAfter(fromBound)) && (!toBound || timestamp.isBefore(toBound))
}

/**
 * Client-side twin of the insights list API filtering (`_filter_request` in
 * products/product_analytics/backend/api/insight.py), so the local draft row obeys the same
 * filters as the saved insights around it.
 */
export function draftInsightMatchesFilters(
    draft: DraftInsightQuery,
    filters: SavedInsightFilters,
    user: UserType | null,
    summaryContext: SummaryContext
): boolean {
    // A draft can never match these: it has no tags, is not favorited, sits on no dashboard, and has never been viewed
    if (filters.favorited || (filters.tags?.length ?? 0) > 0 || !!filters.dashboardId) {
        return false
    }
    if (filters.lastViewedDateFrom && filters.lastViewedDateFrom !== 'all') {
        return false
    }
    // The "Yours" tab and `hideFeatureFlagInsights` need no checks: the draft is always the current
    // user's own, and feature flag insights are excluded by name, which a draft doesn't have.
    // The created-by filter is skipped on the "Yours" tab to match `paramsFromFilters`.
    if (
        filters.tab !== SavedInsightsTabs.Yours &&
        filters.createdBy !== 'All users' &&
        (!user || !filters.createdBy.includes(user.id))
    ) {
        return false
    }
    if (
        filters.insightType.toLowerCase() !== 'all types' &&
        !matchesInsightTypeFilter(draft.query, filters.insightType)
    ) {
        return false
    }
    const timestamp = dayjs(draft.timestamp)
    if (
        filters.dateFrom &&
        filters.dateFrom !== 'all' &&
        !timestampWithinRange(timestamp, filters.dateFrom, filters.dateTo)
    ) {
        return false
    }
    if (
        filters.createdDateFrom &&
        filters.createdDateFrom !== 'all' &&
        !timestampWithinRange(timestamp, filters.createdDateFrom, filters.createdDateTo)
    ) {
        return false
    }
    if (filters.search) {
        // Match against what the row actually displays for the draft
        const displayName = summarizeInsight(draft.query, summaryContext) || DRAFT_INSIGHT_FALLBACK_NAME
        return displayName.toLowerCase().includes(filters.search.toLowerCase())
    }
    return true
}

/** Shapes the local draft like a saved insight so it can sit in the saved insights table. */
export function draftInsightListItem(draft: DraftInsightQuery, currentUser: UserType | null): SavedInsightListItem {
    const timestamp = dayjs(draft.timestamp).toISOString()
    // UserType is not assignable to UserBasicType (hedgehog_config shapes differ), so pick the basic fields
    const user: UserBasicType | null = currentUser
        ? {
              id: currentUser.id,
              uuid: currentUser.uuid,
              distinct_id: currentUser.distinct_id,
              first_name: currentUser.first_name,
              last_name: currentUser.last_name,
              email: currentUser.email,
          }
        : null
    return {
        id: DRAFT_INSIGHT_ROW_ID,
        // Never used for API calls or links: render paths guard via isDraftInsightRow
        short_id: 'draft' as InsightShortId,
        name: '',
        query: draft.query,
        order: null,
        result: null,
        deleted: false,
        saved: false,
        is_sample: false,
        dashboards: null,
        dashboard_tiles: null,
        last_refresh: null,
        created_at: timestamp,
        created_by: user,
        updated_at: timestamp,
        last_modified_at: timestamp,
        last_modified_by: user,
        last_viewed_at: null,
        tags: [],
        favorited: false,
        user_access_level: AccessControlLevel.Viewer,
    }
}
