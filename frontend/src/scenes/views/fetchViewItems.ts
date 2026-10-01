import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { canvasesList } from 'products/canvas/frontend/generated/api'
import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
import { dashboardsList } from 'products/dashboards/frontend/generated/api'
import { notebooksList } from 'products/notebooks/frontend/generated/api'
import type { NotebooksListParams } from 'products/notebooks/frontend/generated/api.schemas'
import { taskChannelsList } from 'products/tasks/frontend/generated/api'
import type { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { LISTED_CANVAS_KINDS, ViewItem, ViewType, mergeViews } from './viewsUtils'

// Each type loads up to this many views. The dashboards endpoint sorts by name rather than by recency, so this
// also bounds how far back the dashboards reach.
const VIEWS_PER_TYPE = 100

export interface ViewItemsPage {
    items: ViewItem[]
    /** Types whose request failed. The list holds the other types only. */
    failedTypes: ViewType[]
}

async function fetchCanvases(projectId: string, search: string | undefined, limit: number): Promise<CanvasApi[]> {
    const pages = await Promise.all(LISTED_CANVAS_KINDS.map((kind) => canvasesList(projectId, { kind, search, limit })))
    return pages.flatMap((page) => page.results)
}

async function fetchSpaceNames(projectId: string): Promise<Record<string, string>> {
    const response = await taskChannelsList(projectId)
    // Without `limit` the endpoint answers with a bare array rather than a page.
    const spaces = Array.isArray(response) ? (response as ChannelDTOApi[]) : response.results
    return Object.fromEntries(spaces.map((space) => [space.id, spaceLabel(space)]))
}

/** Canvases, notebooks and dashboards in one list. A type that fails to load leaves the others in place. */
export async function fetchViewItems(projectId: string, search: string): Promise<ViewItemsPage> {
    const limit = VIEWS_PER_TYPE
    const query = search.trim() || undefined
    // The notebooks endpoint filters on `search`, but its schema does not declare the parameter.
    const notebookParams: NotebooksListParams & { search?: string } = { limit, search: query }
    const [canvases, notebooks, dashboards, spaceNames] = await Promise.allSettled([
        fetchCanvases(projectId, query, limit),
        notebooksList(projectId, notebookParams),
        dashboardsList(projectId, { search: query, limit }),
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
            canvases: canvases.status === 'fulfilled' ? canvases.value : [],
            notebooks: notebooks.status === 'fulfilled' ? notebooks.value.results : [],
            dashboards: dashboards.status === 'fulfilled' ? dashboards.value.results : [],
            // Without space names, canvas rows still show. They only lose the space label.
            spaceNames: spaceNames.status === 'fulfilled' ? spaceNames.value : {},
        }),
        failedTypes,
    }
}
