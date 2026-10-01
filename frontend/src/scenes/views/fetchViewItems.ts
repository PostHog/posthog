import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { canvasesList } from 'products/canvas/frontend/generated/api'
import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
import { dashboardsList } from 'products/dashboards/frontend/generated/api'
import { notebooksList } from 'products/notebooks/frontend/generated/api'
import type { NotebooksListParams } from 'products/notebooks/frontend/generated/api.schemas'
import { taskChannelsList } from 'products/tasks/frontend/generated/api'
import type { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { LISTED_CANVAS_KINDS, ViewItem, ViewType, mergeViews } from './viewsUtils'

const VIEWS_PAGE_SIZE = 100
const MAX_VIEW_PAGES = 5

export interface ViewItemsPage {
    items: ViewItem[]
    /** Types whose request failed. The list holds the other types only. */
    failedTypes: ViewType[]
    truncated?: boolean
}

async function fetchViewPages<T>(
    fetchPage: (offset: number) => Promise<{ results: T[]; next?: string | null }>
): Promise<{ items: T[]; truncated: boolean }> {
    const results: T[] = []
    let page
    for (let pageIndex = 0; pageIndex < MAX_VIEW_PAGES; pageIndex++) {
        page = await fetchPage(results.length)
        results.push(...page.results)
        if (!page.next || page.results.length === 0) {
            return { items: results, truncated: false }
        }
    }
    return { items: results, truncated: true }
}

async function fetchCanvases(
    projectId: string,
    search: string | undefined,
    limit: number
): Promise<{ items: CanvasApi[]; truncated: boolean }> {
    const pages = await Promise.all(
        LISTED_CANVAS_KINDS.map((kind) =>
            fetchViewPages((offset) => canvasesList(projectId, { kind, search, limit, offset }))
        )
    )
    return { items: pages.flatMap((page) => page.items), truncated: pages.some((page) => page.truncated) }
}

async function fetchSpaceNames(projectId: string): Promise<Record<string, string>> {
    const response = await taskChannelsList(projectId)
    // Without `limit` the endpoint answers with a bare array rather than a page.
    const spaces = Array.isArray(response) ? (response as ChannelDTOApi[]) : response.results
    return Object.fromEntries(spaces.map((space) => [space.id, spaceLabel(space)]))
}

/** Canvases, notebooks and dashboards in one list. A type that fails to load leaves the others in place. */
export async function fetchViewItems(projectId: string, search: string): Promise<ViewItemsPage> {
    const limit = VIEWS_PAGE_SIZE
    const query = search.trim() || undefined
    // The notebooks endpoint filters on `search`, but its schema does not declare the parameter.
    const notebookParams: NotebooksListParams & { search?: string } = { limit, search: query }
    const [canvases, notebooks, dashboards, spaceNames] = await Promise.allSettled([
        fetchCanvases(projectId, query, limit),
        fetchViewPages((offset) => notebooksList(projectId, { ...notebookParams, offset })),
        fetchViewPages((offset) => dashboardsList(projectId, { search: query, limit, offset })),
        fetchSpaceNames(projectId),
    ])
    const failedTypes: ViewType[] = [
        ...(canvases.status === 'rejected' ? (['canvas'] as const) : []),
        ...(notebooks.status === 'rejected' ? (['notebook'] as const) : []),
        ...(dashboards.status === 'rejected' ? (['dashboard'] as const) : []),
    ]
    if (failedTypes.length === 3) {
        throw canvases.status === 'rejected' ? canvases.reason : new Error('Views did not load')
    }
    return {
        items: mergeViews({
            canvases: canvases.status === 'fulfilled' ? canvases.value.items : [],
            notebooks: notebooks.status === 'fulfilled' ? notebooks.value.items : [],
            dashboards: dashboards.status === 'fulfilled' ? dashboards.value.items : [],
            // Without space names, canvas rows still show. They only lose the space label.
            spaceNames: spaceNames.status === 'fulfilled' ? spaceNames.value : {},
        }),
        failedTypes,
        truncated: [canvases, notebooks, dashboards].some(
            (result) => result.status === 'fulfilled' && result.value.truncated
        ),
    }
}
