import api from 'lib/api'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import {
    ANALYTICS_TYPES,
    AnalyticsItem,
    AnalyticsType,
    AnalyticsTypeFilter,
    fileSystemEntryToAnalytics,
} from './analyticsUtils'

export const ANALYTICS_FEED_PAGE_SIZE = 50

/** A creator, by both identifiers: some product APIs filter on `id`, the file system rows carry `uuid`. */
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

// Insights file as `insight` or under a subtype such as `insight/trends`, so they match on the prefix.
export function fileSystemTypeParams(type: AnalyticsType): { type?: string; type__startswith?: string } {
    return type === 'insight' ? { type__startswith: 'insight' } : { type }
}

/** One page of a type's rows from the project file system, newest first, with the row's space. */
export async function fetchAnalyticsSourcePage(
    _projectId: string,
    type: AnalyticsType,
    query: AnalyticsFeedQuery,
    offset: number
): Promise<AnalyticsSourcePage> {
    const limit = ANALYTICS_FEED_PAGE_SIZE
    const result = await api.fileSystem.list({
        ...fileSystemTypeParams(type),
        search: query.search.trim() || undefined,
        orderBy: '-created_at',
        limit,
        offset,
    })
    const items = result.results.flatMap((entry: FileSystemEntry) => {
        const item = fileSystemEntryToAnalytics(entry, result.users ?? [])
        return item && matchesAnalyticsQuery(item, query) ? [item] : []
    })
    return { items, fetched: result.results.length, hasMore: !!result.next && result.results.length > 0 }
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
