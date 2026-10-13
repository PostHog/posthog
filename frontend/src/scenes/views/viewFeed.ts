import { canvasesList } from 'products/canvas/frontend/generated/api'
import { dashboardsList } from 'products/dashboards/frontend/generated/api'
import { notebooksList } from 'products/notebooks/frontend/generated/api'
import type { NotebooksListParams } from 'products/notebooks/frontend/generated/api.schemas'

import {
    LISTED_CANVAS_KIND,
    VIEW_TYPES,
    ViewItem,
    ViewType,
    ViewTypeFilter,
    canvasToView,
    dashboardToView,
    notebookToView,
} from './viewsUtils'

export const VIEW_FEED_PAGE_SIZE = 50

export interface ViewFeedQuery {
    type: ViewTypeFilter
    search: string
}

export interface ViewSourcePage {
    items: ViewItem[]
    fetched: number
    hasMore: boolean
}

export interface ViewSourceState {
    projectId: string
    search: string
    type: ViewType
    items: ViewItem[]
    offset: number
    hasMore: boolean
    initialized: boolean
    refreshing: boolean
    loading: boolean
    failed: boolean
    generation: number
}

export interface ViewFeed {
    items: ViewItem[]
    initialized: boolean
    loading: boolean
    hasMore: boolean
    failedTypes: ViewType[]
    loadFailed: boolean
}

export function viewFeedTypes(query: ViewFeedQuery): ViewType[] {
    return query.type === 'all' ? VIEW_TYPES.map((info) => info.type) : [query.type]
}

export function viewSourceKey(projectId: string, search: string, type: ViewType): string {
    return JSON.stringify([projectId, search.trim(), type])
}

export async function fetchViewSourcePage(
    projectId: string,
    type: ViewType,
    search: string,
    offset: number
): Promise<ViewSourcePage> {
    const limit = VIEW_FEED_PAGE_SIZE
    const query = search.trim() || undefined
    if (type === 'canvas') {
        const page = await canvasesList(projectId, {
            kind: LISTED_CANVAS_KIND,
            search: query,
            ordering: '-updated_at',
            limit,
            offset,
        })
        return {
            items: page.results.map((canvas) => canvasToView(canvas, {})),
            fetched: page.results.length,
            hasMore: !!page.next && page.results.length > 0,
        }
    }
    if (type === 'notebook') {
        // The notebooks endpoint filters on `search`, but its schema does not declare the parameter.
        const params: NotebooksListParams & { search?: string } = { limit, offset, search: query }
        const page = await notebooksList(projectId, params)
        return {
            items: page.results.filter((notebook) => !notebook.deleted).map(notebookToView),
            fetched: page.results.length,
            hasMore: !!page.next && page.results.length > 0,
        }
    }
    const page = await dashboardsList(projectId, { search: query, ordering: '-last_viewed_at', limit, offset })
    return {
        items: page.results.filter((dashboard) => !dashboard.deleted).map(dashboardToView),
        fetched: page.results.length,
        hasMore: !!page.next && page.results.length > 0,
    }
}

export function viewTime(item: ViewItem): number {
    return item.timestamp ? new Date(item.timestamp).getTime() : 0
}

export function mergeViewSources(sources: (ViewSourceState | undefined)[]): {
    items: ViewItem[]
    blocking: ViewSourceState[]
} {
    const states = sources.map(
        (source) => source ?? ({ items: [], hasMore: true, initialized: false } as unknown as ViewSourceState)
    )
    const positions = states.map(() => 0)
    const items: ViewItem[] = []
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
                    viewTime(states[index].items[positions[index]]) > viewTime(states[best].items[positions[best]]))
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

export function viewFeedFromSources(
    sources: (ViewSourceState | undefined)[],
    spaceNames: Record<string, string>
): ViewFeed {
    const { items, blocking } = mergeViewSources(sources)
    const initialized = sources.every((source) => source?.initialized)
    const failed = sources.filter((source): source is ViewSourceState => !!source?.failed)
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
