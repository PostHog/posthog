import api from 'lib/api'

import { AnalyticsListDisplayConfiguration, FileSystemEntry } from '~/queries/schema/schema-general'

import { ANALYTICS_TYPES, AnalyticsItem, AnalyticsType, fileSystemEntryToAnalytics } from './analyticsUtils'

export const ANALYTICS_FEED_PAGE_SIZE = 20

const ANALYTICS_ORDER_BYS = [
    '-created_at',
    'created_at',
    '-last_viewed_at',
    'last_viewed_at',
    '-view_count',
    '-viewer_count',
] as const

/** A column of the list, with a leading `-` for descending, as the file system API takes it. */
export type AnalyticsOrderBy = (typeof ANALYTICS_ORDER_BYS)[number]

export function isAnalyticsOrderBy(value: unknown): value is AnalyticsOrderBy {
    return ANALYTICS_ORDER_BYS.includes(value as AnalyticsOrderBy)
}

/** The orders saved as the person's default: newest or most first. Oldest first only lasts for the visit. */
export function isAnalyticsDefaultSort(
    orderBy: AnalyticsOrderBy
): orderBy is NonNullable<AnalyticsListDisplayConfiguration['default_sort']> {
    return orderBy.startsWith('-')
}

/** Orders on a count over the last 30 days rather than on a time. */
export function isAnalyticsCountOrderBy(orderBy: AnalyticsOrderBy | undefined): boolean {
    return orderBy === '-view_count' || orderBy === '-viewer_count'
}

export function parseAnalyticsOrderBy(orderBy: AnalyticsOrderBy): { id: string; desc: boolean } {
    return { id: orderBy.replace('-', ''), desc: orderBy.startsWith('-') }
}

/** The order for a sorted column, or undefined for a column the list cannot sort on. */
export function analyticsOrderByOfColumn({ id, desc }: { id: string; desc: boolean }): AnalyticsOrderBy | undefined {
    const orderBy = `${desc ? '-' : ''}${id}`
    return isAnalyticsOrderBy(orderBy) ? orderBy : undefined
}

export interface AnalyticsFeedQuery {
    /** The types to list; empty means every type. */
    types: AnalyticsType[]
    orderBy?: AnalyticsOrderBy
    search: string
    /** Creators' uuids; empty means anyone. The file system cannot filter on a uuid, so the rows are narrowed on the client. */
    createdBy: string[]
    /** True when the only creator is the current person, so the file system narrows the rows itself with `user:me`. */
    createdByMe: boolean
    /** Tag names a row must all carry. Like the creator, narrowed on the client. */
    tags: string[]
    /** Leaves insights out of the list of every type. Picking the insight type still shows them. */
    hideInsights?: boolean
    /** Asks for each row's views and viewers, which a shown count column needs whatever the order. */
    includeViewCounts?: boolean
}

export const EMPTY_ANALYTICS_FEED_QUERY: AnalyticsFeedQuery = {
    types: [],
    search: '',
    createdBy: [],
    createdByMe: false,
    tags: [],
}

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

// Only dashboards and insights carry tags, so a tag filter leaves the other types out of the read.
const TAGGABLE_ANALYTICS_TYPES: ReadonlySet<AnalyticsType> = new Set<AnalyticsType>(['dashboard', 'insight'])

export function analyticsFeedTypes(query: AnalyticsFeedQuery): AnalyticsType[] {
    const types = query.types.length
        ? query.types
        : ANALYTICS_TYPES.map((info) => info.type).filter((type) => !query.hideInsights || type !== 'insight')
    return query.tags.length ? types.filter((type) => TAGGABLE_ANALYTICS_TYPES.has(type)) : types
}

export function analyticsSourceKey(projectId: string, query: AnalyticsFeedQuery, type: AnalyticsType): string {
    return JSON.stringify([
        projectId,
        query.search.trim(),
        query.createdBy,
        [...query.tags].sort(),
        type,
        query.orderBy ?? '-created_at',
        !!query.includeViewCounts,
    ])
}

/** Keeps the rows a source's API could not filter itself. */
export function matchesAnalyticsQuery(item: AnalyticsItem, query: AnalyticsFeedQuery): boolean {
    return (
        (!query.createdBy.length || (!!item.createdBy && query.createdBy.includes(item.createdBy.uuid))) &&
        query.tags.every((tag) => item.tags.includes(tag))
    )
}

// Insights file as `insight` or under a subtype such as `insight/trends`, so they match on the prefix.
export function fileSystemTypeParams(type: AnalyticsType): { type?: string; type__startswith?: string } {
    return type === 'insight' ? { type__startswith: 'insight' } : { type }
}

/** One page of a type's rows from the project file system, in the requested order, with the row's space. */
export async function fetchAnalyticsSourcePage(
    _projectId: string,
    type: AnalyticsType,
    query: AnalyticsFeedQuery,
    offset: number
): Promise<AnalyticsSourcePage> {
    const limit = ANALYTICS_FEED_PAGE_SIZE
    // Without the server filter, a person's rows hide among everyone else's and each page brings few of them.
    const search = [query.createdByMe ? 'user:me' : '', query.search.trim()].filter(Boolean).join(' ')
    const result = await api.fileSystem.list({
        ...fileSystemTypeParams(type),
        search: search || undefined,
        orderBy: query.orderBy ?? '-created_at',
        includeTags: true,
        includeViewCounts: query.includeViewCounts || undefined,
        limit,
        offset,
    })
    const items = result.results.flatMap((entry: FileSystemEntry) => {
        const item = fileSystemEntryToAnalytics(entry, result.users ?? [])
        if (!item || !matchesAnalyticsQuery(item, query)) {
            return []
        }
        if (query.orderBy && parseAnalyticsOrderBy(query.orderBy).id === 'last_viewed_at') {
            item.timestamp = entry.last_viewed_at ?? null
        }
        if (isAnalyticsCountOrderBy(query.orderBy) || query.includeViewCounts) {
            item.viewCount = entry.view_count ?? 0
            item.viewerCount = entry.viewer_count ?? 0
        }
        return [item]
    })
    return { items, fetched: result.results.length, hasMore: !!result.next && result.results.length > 0 }
}

/** The value the feed merges each type's rows on, larger first. */
export function analyticsSortValue(item: AnalyticsItem, orderBy?: AnalyticsFeedQuery['orderBy']): number {
    if (orderBy === '-view_count') {
        return item.viewCount ?? 0
    }
    if (orderBy === '-viewer_count') {
        return item.viewerCount ?? 0
    }
    if (!item.timestamp) {
        return -Infinity
    }
    const time = new Date(item.timestamp).getTime()
    return orderBy && !parseAnalyticsOrderBy(orderBy).desc ? -time : time
}

function analyticsItemComesFirst(
    first: AnalyticsItem,
    second: AnalyticsItem,
    orderBy?: AnalyticsFeedQuery['orderBy']
): boolean {
    const firstValue = analyticsSortValue(first, orderBy)
    const secondValue = analyticsSortValue(second, orderBy)
    if (firstValue !== secondValue) {
        return firstValue > secondValue
    }
    return new Date(first.createdAt ?? 0).getTime() > new Date(second.createdAt ?? 0).getTime()
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
                    analyticsItemComesFirst(
                        states[index].items[positions[index]],
                        states[best].items[positions[best]],
                        states[index].query?.orderBy
                    ))
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

export function analyticsFeedFromSources(sources: (AnalyticsSourceState | undefined)[]): AnalyticsFeed {
    const { items, blocking } = mergeAnalyticsSources(sources)
    const initialized = sources.every((source) => source?.initialized)
    const failed = sources.filter((source): source is AnalyticsSourceState => !!source?.failed)
    return {
        items: initialized ? items : [],
        initialized,
        loading: sources.some((source) => !source || source.loading || source.refreshing),
        hasMore: blocking.length > 0,
        failedTypes: failed.map((source) => source.type),
        // A tag filter on untaggable types leaves no sources at all, which is an empty list and not a failure.
        loadFailed: initialized && sources.length > 0 && failed.length === sources.length && items.length === 0,
    }
}
