import { canvasesList } from 'products/canvas/frontend/generated/api'
import { dashboardsList } from 'products/dashboards/frontend/generated/api'
import { notebooksList } from 'products/notebooks/frontend/generated/api'
import type { NotebooksListParams } from 'products/notebooks/frontend/generated/api.schemas'
import { insightsList } from 'products/product_analytics/frontend/generated/api'
import type { InsightsListParams } from 'products/product_analytics/frontend/generated/api.schemas'

import {
    ANALYTICS_TYPES,
    AnalyticsItem,
    AnalyticsType,
    AnalyticsTypeFilter,
    LISTED_CANVAS_KIND,
    canvasToAnalytics,
    dashboardToAnalytics,
    insightToAnalytics,
    notebookToAnalytics,
} from './analyticsUtils'

export const ANALYTICS_FEED_PAGE_SIZE = 50

/** A creator, by both identifiers: the insights API filters on `id`, the notebooks API and the rows on `uuid`. */
export interface AnalyticsCreator {
    uuid: string
    /** Null until the member list resolves it; the rows are then narrowed on the client instead. */
    id: number | null
}

export interface AnalyticsFeedQuery {
    type: AnalyticsTypeFilter
    search: string
    createdBy: AnalyticsCreator | null
    tags: string[]
}

export const EMPTY_ANALYTICS_FEED_QUERY: AnalyticsFeedQuery = { type: 'all', search: '', createdBy: null, tags: [] }

export interface AnalyticsSourcePage {
    items: AnalyticsItem[]
    /** Rows the API returned, before any client-side filtering, so the next offset stays right. */
    fetched: number
    hasMore: boolean
}

export interface AnalyticsSourceState {
    projectId: string
    query: AnalyticsFeedQuery
    type: AnalyticsType
    items: AnalyticsItem[]
    offset: number
    hasMore: boolean
    initialized: boolean
    refreshing: boolean
    loading: boolean
    failed: boolean
    generation: number
}

export interface AnalyticsFeed {
    items: AnalyticsItem[]
    initialized: boolean
    loading: boolean
    hasMore: boolean
    failedTypes: AnalyticsType[]
    loadFailed: boolean
}

export function analyticsFeedTypes(query: AnalyticsFeedQuery): AnalyticsType[] {
    return query.type === 'all' ? ANALYTICS_TYPES.map((info) => info.type) : [query.type]
}

export function analyticsSourceKey(projectId: string, query: AnalyticsFeedQuery, type: AnalyticsType): string {
    return JSON.stringify([projectId, query.search.trim(), query.createdBy?.uuid ?? null, [...query.tags].sort(), type])
}

/** Keeps the rows a source's API could not filter itself. */
export function matchesAnalyticsQuery(item: AnalyticsItem, query: AnalyticsFeedQuery): boolean {
    return (
        (!query.createdBy || item.createdBy?.uuid === query.createdBy.uuid) &&
        query.tags.every((tag) => item.tags.includes(tag))
    )
}

export async function fetchAnalyticsSourcePage(
    projectId: string,
    type: AnalyticsType,
    query: AnalyticsFeedQuery,
    offset: number
): Promise<AnalyticsSourcePage> {
    const limit = ANALYTICS_FEED_PAGE_SIZE
    const search = query.search.trim() || undefined
    const page = (items: AnalyticsItem[], fetched: number, next: string | null | undefined): AnalyticsSourcePage => ({
        items: items.filter((item) => matchesAnalyticsQuery(item, query)),
        fetched,
        hasMore: !!next && fetched > 0,
    })
    if (type === 'canvas') {
        // Canvases carry no tags, so a tag filter cannot match one.
        if (query.tags.length) {
            return { items: [], fetched: 0, hasMore: false }
        }
        const result = await canvasesList(projectId, {
            kind: LISTED_CANVAS_KIND,
            search,
            ordering: '-updated_at',
            limit,
            offset,
        })
        return page(
            result.results.map((canvas) => canvasToAnalytics(canvas, {})),
            result.results.length,
            result.next
        )
    }
    if (type === 'notebook') {
        if (query.tags.length) {
            return { items: [], fetched: 0, hasMore: false }
        }
        // The notebooks endpoint filters on `search`, but its schema does not declare the parameter.
        const params: NotebooksListParams & { search?: string } = {
            limit,
            offset,
            search,
            created_by: query.createdBy?.uuid,
        }
        const result = await notebooksList(projectId, params)
        return page(
            result.results.filter((notebook) => !notebook.deleted).map(notebookToAnalytics),
            result.results.length,
            result.next
        )
    }
    if (type === 'insight') {
        // The insights endpoint sorts on `order`, but its schema does not declare the parameter.
        const params: InsightsListParams & { order: string } = {
            basic: true,
            saved: true,
            search,
            created_by: query.createdBy?.id != null ? JSON.stringify([query.createdBy.id]) : undefined,
            tags: query.tags.length ? JSON.stringify(query.tags) : undefined,
            order: '-last_modified_at',
            limit,
            offset,
        }
        const result = await insightsList(projectId, params)
        return page(result.results.map(insightToAnalytics), result.results.length, result.next)
    }
    const result = await dashboardsList(projectId, { search, ordering: '-last_viewed_at', limit, offset })
    return page(
        result.results.filter((dashboard) => !dashboard.deleted).map(dashboardToAnalytics),
        result.results.length,
        result.next
    )
}

export function analyticsTime(item: AnalyticsItem): number {
    return item.timestamp ? new Date(item.timestamp).getTime() : 0
}

export function mergeAnalyticsSources(sources: (AnalyticsSourceState | undefined)[]): {
    items: AnalyticsItem[]
    blocking: AnalyticsSourceState[]
} {
    const states = sources.map(
        (source) => source ?? ({ items: [], hasMore: true, initialized: false } as unknown as AnalyticsSourceState)
    )
    const positions = states.map(() => 0)
    const items: AnalyticsItem[] = []
    for (;;) {
        const blocking = states.filter(
            (state, index) => positions[index] >= state.items.length && (state.hasMore || !state.initialized)
        )
        if (blocking.length) {
            return { items, blocking: blocking.filter((state) => sources.includes(state)) }
        }
        let best = -1
        for (let index = 0; index < states.length; index++) {
            if (
                positions[index] < states[index].items.length &&
                (best === -1 ||
                    analyticsTime(states[index].items[positions[index]]) >
                        analyticsTime(states[best].items[positions[best]]))
            ) {
                best = index
            }
        }
        if (best === -1) {
            return { items, blocking: [] }
        }
        items.push(states[best].items[positions[best]++])
    }
}

export function analyticsFeedFromSources(
    sources: (AnalyticsSourceState | undefined)[],
    spaceNames: Record<string, string>
): AnalyticsFeed {
    const { items, blocking } = mergeAnalyticsSources(sources)
    const initialized = sources.every((source) => source?.initialized)
    const failed = sources.filter((source): source is AnalyticsSourceState => !!source?.failed)
    return {
        items: initialized
            ? items.map((item) =>
                  item.spaceId && !item.spaceName && spaceNames[item.spaceId]
                      ? { ...item, spaceName: spaceNames[item.spaceId] }
                      : item
              )
            : [],
        initialized,
        loading: sources.some((source) => !source || source.loading || source.refreshing),
        hasMore: blocking.length > 0,
        failedTypes: failed.map((source) => source.type),
        loadFailed: initialized && failed.length === sources.length && items.length === 0,
    }
}
