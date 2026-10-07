import { urls } from 'scenes/urls'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
import type { DashboardBasicApi } from 'products/dashboards/frontend/generated/api.schemas'
import type { NotebookMinimalApi } from 'products/notebooks/frontend/generated/api.schemas'

// pinned: these values are the `type` property of the `views new picked` and `views list filtered` events.
export type ViewType = 'canvas' | 'notebook' | 'dashboard'
export type ViewTypeFilter = ViewType | 'all'

export interface ViewTypeInfo {
    type: ViewType
    label: string
    pluralLabel: string
    /** One line for the "New" menu. */
    description: string
}

export const VIEW_TYPES: ViewTypeInfo[] = [
    {
        type: 'canvas',
        label: 'Canvas',
        pluralLabel: 'Canvases',
        description: 'A freeform page that AI builds from your prompt',
    },
    {
        type: 'notebook',
        label: 'Notebook',
        pluralLabel: 'Notebooks',
        description: 'A doc that mixes your notes with live insights and replays',
    },
    {
        type: 'dashboard',
        label: 'Dashboard',
        pluralLabel: 'Dashboards',
        description: 'A grid of saved insights for your key metrics',
    },
]

export const VIEW_TYPE_INFO = Object.fromEntries(VIEW_TYPES.map((info) => [info.type, info])) as Record<
    ViewType,
    ViewTypeInfo
>

// Component canvases are widgets that grids place, not views a person opens.
export const LISTED_CANVAS_KIND = 'freeform'

export interface ViewItem {
    type: ViewType
    id: string
    name: string
    href: string
    /** When the view last changed, or was last viewed or created when that is all the API knows. */
    timestamp: string | null
    timestampLabel: 'Edited' | 'Viewed' | 'Created'
    /** The space a canvas belongs to. Null for other types. */
    spaceId: string | null
    /** The space's name. Null for other types, or when the space is unknown. */
    spaceName: string | null
    createdByUuid: string | null
    /** The run building a canvas that has no version yet. Null once it has one, and for other types. */
    firstBuildTaskId: string | null
}

export function canvasToView(canvas: CanvasApi, spaceNames: Record<string, string>): ViewItem {
    return {
        type: 'canvas',
        id: canvas.id,
        name: canvas.name || 'Untitled canvas',
        href: urls.canvasDetail(canvas.id),
        timestamp: canvas.updated_at,
        timestampLabel: 'Edited',
        spaceId: canvas.channel,
        spaceName: spaceNames[canvas.channel] ?? null,
        createdByUuid: canvas.created_by?.uuid ?? null,
        firstBuildTaskId: canvas.current_version_id ? null : (canvas.generation_task_id ?? null),
    }
}

export function notebookToView(notebook: NotebookMinimalApi): ViewItem {
    return {
        type: 'notebook',
        id: notebook.short_id,
        name: notebook.title || 'Untitled notebook',
        href: urls.notebook(notebook.short_id),
        timestamp: notebook.last_modified_at,
        timestampLabel: 'Edited',
        spaceId: null,
        spaceName: null,
        createdByUuid: notebook.created_by?.uuid ?? null,
        firstBuildTaskId: null,
    }
}

export function dashboardToView(dashboard: DashboardBasicApi): ViewItem {
    return {
        type: 'dashboard',
        id: String(dashboard.id),
        name: dashboard.name || 'Untitled dashboard',
        href: urls.dashboard(dashboard.id),
        // Dashboards have no edit time in the list API, so the last view stands in for it.
        timestamp: dashboard.last_viewed_at ?? dashboard.created_at,
        timestampLabel: dashboard.last_viewed_at ? 'Viewed' : 'Created',
        spaceId: null,
        spaceName: null,
        createdByUuid: dashboard.created_by?.uuid ?? null,
        firstBuildTaskId: null,
    }
}

/**
 * The space a new canvas defaults to from the page the person is on: the open space, or the open
 * canvas's space. Null when the page names no space, so the start page falls back to the personal space.
 */
export function newCanvasSpaceIdForPath(
    path: string,
    openCanvas: Pick<CanvasApi, 'id' | 'channel'> | null
): string | null {
    const space = /^\/spaces\/([^/]+)/.exec(path)
    if (space) {
        return space[1]
    }
    const canvas = /^\/canvases\/([^/]+)$/.exec(path)
    return canvas && openCanvas?.id === canvas[1] ? openCanvas.channel : null
}
