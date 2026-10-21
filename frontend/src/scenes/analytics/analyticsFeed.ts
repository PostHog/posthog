import api from 'lib/api'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import {
    ANALYTICS_TYPES,
    AnalyticsItem,
    AnalyticsType,
    AnalyticsTypeFilter,
    fileSystemEntryToAnalytics,
} from './analyticsUtils'

export const ANALYTICS_FEED_PAGE_SIZE = 20

export interface AnalyticsFeedQuery {
    type: AnalyticsTypeFilter
    orderBy?: '-created_at' | '-last_viewed_at' | 'last_viewed_at'
    search: string
    /** Creators' uuids; empty means anyone. The file system cannot filter on a uuid, so the rows are narrowed on the client. */
    createdBy: string[]
    /** True when the only creator is the current person, so the file system narrows the rows itself with `user:me`. */
    createdByMe: boolean
    /** Tag names a row must all carry. Like the creator, narrowed on the client. */
    tags: string[]
}

export const EMPTY_ANALYTICS_FEED_QUERY: AnalyticsFeedQuery = {
    type: 'all',
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
    const types = query.type === 'all' ? ANALYTICS_TYPES.map((info) => info.type) : [query.type]
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
        limit,
        offset,
    })
    const items = result.results.flatMap((entry: FileSystemEntry) => {
        const item = fileSystemEntryToAnalytics(entry, result.users ?? [])
        if (!item || !matchesAnalyticsQuery(item, query)) {
            return []
        }
        if (query.orderBy && query.orderBy !== '-created_at') {
            item.timestamp = entry.last_viewed_at ?? null
        }
        return [item]
    })
    return { items, fetched: result.results.length, hasMore: !!result.next && result.results.length > 0 }
}

export function analyticsTime(item: AnalyticsItem, orderBy?: AnalyticsFeedQuery['orderBy']): number {
    if (!item.timestamp) {
        return -Infinity
    }
    const time = new Date(item.timestamp).getTime()
    return orderBy === 'last_viewed_at' ? -time : time
}

function analyticsItemComesFirst(
    first: AnalyticsItem,
    second: AnalyticsItem,
    orderBy?: AnalyticsFeedQuery['orderBy']
): boolean {
    const firstTime = analyticsTime(first, orderBy)
    const secondTime = analyticsTime(second, orderBy)
    if (firstTime !== secondTime) {
        return firstTime > secondTime
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
        loadFailed: initialized && failed.length === sources.length && items.length === 0,
    }
}
