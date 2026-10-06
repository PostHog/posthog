import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { fileSystemTypes, getTreeItemsProducts } from '~/products'
import { FileSystemEntry, FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'
import type { InsightShortId, UserBasicType } from '~/types'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
import type { DashboardBasicApi } from 'products/dashboards/frontend/generated/api.schemas'
import type { NotebookMinimalApi } from 'products/notebooks/frontend/generated/api.schemas'
import type { InsightApi } from 'products/product_analytics/frontend/generated/api.schemas'

// pinned: these values are the `type` property of the `views new picked` and `views list filtered` events.
export type AnalyticsType = 'canvas' | 'notebook' | 'dashboard' | 'insight'
export type AnalyticsTypeFilter = AnalyticsType | 'all'

export interface AnalyticsTypeInfo {
    type: AnalyticsType
    label: string
    pluralLabel: string
    description: string
}

export const ANALYTICS_TYPES: AnalyticsTypeInfo[] = [
    {
        type: 'canvas',
        label: 'Canvas',
        pluralLabel: 'Canvases',
        description: 'A freeform page that AI builds from your prompt',
    },
    {
        type: 'dashboard',
        label: 'Dashboard',
        pluralLabel: 'Dashboards',
        description: 'A grid of saved insights for your key metrics',
    },
    {
        type: 'notebook',
        label: 'Notebook',
        pluralLabel: 'Notebooks',
        description: 'A doc that mixes your notes with live insights and replays',
    },
    {
        type: 'insight',
        label: 'Insight',
        pluralLabel: 'Insights',
        description: 'One chart or table over your events',
    },
]

export const ANALYTICS_TYPE_INFO = Object.fromEntries(ANALYTICS_TYPES.map((info) => [info.type, info])) as Record<
    AnalyticsType,
    AnalyticsTypeInfo
>

/** The file system types that are analytics, so the project tree and recents can be narrowed to them. */
export const ANALYTICS_FILE_SYSTEM_TYPES: ReadonlySet<string> = new Set<AnalyticsType>(
    ANALYTICS_TYPES.map((info) => info.type)
)

export function isAnalyticsType(type: string): type is AnalyticsType {
    return ANALYTICS_FILE_SYSTEM_TYPES.has(type)
}

/** The project tree icon type for each analytics type, which carries that product's colour. */
export const ANALYTICS_TYPE_ICON_TYPE: Record<AnalyticsType, FileSystemIconType> = {
    canvas: 'canvas',
    dashboard: 'dashboard',
    notebook: 'notebook',
    insight: 'product_analytics',
}

// Component canvases are widgets that grids place, not analytics a person opens.
export const LISTED_CANVAS_KIND = 'freeform'

export interface AnalyticsItem {
    type: AnalyticsType
    id: string
    name: string
    href: string
    /** When the item last changed, or was last viewed or created when that is all the API knows. */
    timestamp: string | null
    timestampLabel: 'Edited' | 'Viewed' | 'Created'
    createdAt: string | null
    /** When anyone in the project last opened it. Null when the API does not track that for the type. */
    lastAccessedAt: string | null
    createdBy: Pick<UserBasicType, 'uuid' | 'first_name' | 'last_name' | 'email'> | null
    tags: string[]
    spaceId: string | null
    spaceName: string | null
    /** The run building a canvas that has no version yet. Null once it has one, and for other types. */
    firstBuildTaskId: string | null
}

export const ANALYTICS_BACK_NAME = 'Analytics'

/** The item's page, told where the person came from so its back control returns there rather than to the type's own list. */
export function analyticsOpenHref(item: Pick<AnalyticsItem, 'href'>, backUrl: string): string {
    return combineUrl(item.href, { backUrl, backName: ANALYTICS_BACK_NAME }).url
}

function stringTags(tags: unknown[] | undefined): string[] {
    return (tags ?? []).filter((tag): tag is string => typeof tag === 'string')
}

type ApiUser = { uuid: string; first_name?: string; last_name?: string; email: string } | null | undefined

function userFromApi(user: ApiUser): AnalyticsItem['createdBy'] {
    return user
        ? { uuid: user.uuid, first_name: user.first_name ?? '', last_name: user.last_name ?? '', email: user.email }
        : null
}

export function canvasToAnalytics(canvas: CanvasApi, spaceNames: Record<string, string>): AnalyticsItem {
    return {
        type: 'canvas',
        id: canvas.id,
        name: canvas.name || 'Untitled canvas',
        href: urls.canvasDetail(canvas.id),
        timestamp: canvas.updated_at,
        timestampLabel: 'Edited',
        createdAt: canvas.created_at ?? null,
        lastAccessedAt: null,
        createdBy: userFromApi(canvas.created_by),
        tags: [],
        spaceId: canvas.channel,
        spaceName: spaceNames[canvas.channel] ?? null,
        firstBuildTaskId: canvas.current_version_id ? null : (canvas.generation_task_id ?? null),
    }
}

export function notebookToAnalytics(notebook: NotebookMinimalApi): AnalyticsItem {
    return {
        type: 'notebook',
        id: notebook.short_id,
        name: notebook.title || 'Untitled notebook',
        href: urls.notebook(notebook.short_id),
        timestamp: notebook.last_modified_at,
        timestampLabel: 'Edited',
        createdAt: notebook.created_at ?? null,
        lastAccessedAt: null,
        createdBy: userFromApi(notebook.created_by),
        tags: [],
        spaceId: null,
        spaceName: null,
        firstBuildTaskId: null,
    }
}

export function dashboardToAnalytics(dashboard: DashboardBasicApi): AnalyticsItem {
    return {
        type: 'dashboard',
        id: String(dashboard.id),
        name: dashboard.name || 'Untitled dashboard',
        href: urls.dashboard(dashboard.id),
        // Dashboards have no edit time in the list API, so the last view stands in for it.
        timestamp: dashboard.last_viewed_at ?? dashboard.created_at,
        timestampLabel: dashboard.last_viewed_at ? 'Viewed' : 'Created',
        createdAt: dashboard.created_at,
        lastAccessedAt: dashboard.last_accessed_at ?? null,
        createdBy: userFromApi(dashboard.created_by),
        tags: stringTags(dashboard.tags),
        spaceId: null,
        spaceName: null,
        firstBuildTaskId: null,
    }
}

export function insightToAnalytics(insight: InsightApi): AnalyticsItem {
    return {
        type: 'insight',
        id: insight.short_id,
        name: insight.name || insight.derived_name || 'Untitled insight',
        href: urls.insightView(insight.short_id as InsightShortId),
        timestamp: insight.last_modified_at,
        timestampLabel: 'Edited',
        createdAt: insight.created_at ?? null,
        lastAccessedAt: insight.last_viewed_at ?? null,
        createdBy: userFromApi(insight.created_by),
        tags: stringTags(insight.tags),
        spaceId: null,
        spaceName: null,
        firstBuildTaskId: null,
    }
}

/** The last segment of a file system path, with escaped slashes restored. */
export function fileSystemEntryName(entry: Pick<FileSystemEntry, 'path'>): string {
    const segments = entry.path.split(/(?<!\\)\//)
    return (segments[segments.length - 1] || entry.path).replace(/\\\//g, '/')
}

/** The base type of a file system entry: `insight/trends` is an `insight`. */
export function fileSystemBaseType(type: string | undefined): string {
    return type?.split('/')[0] ?? ''
}

/**
 * An analytics item from its file system row, for the folder tree and recents. The row knows the
 * creator and the person's own last view, but no tags and no project-wide access time.
 */
export function fileSystemEntryToAnalytics(
    entry: FileSystemEntry,
    users: Pick<UserBasicType, 'id' | 'uuid' | 'first_name' | 'last_name' | 'email'>[] = []
): AnalyticsItem | null {
    const type = fileSystemBaseType(entry.type)
    if (!isAnalyticsType(type) || !entry.ref) {
        return null
    }
    const definition = fileSystemTypes[type as keyof typeof fileSystemTypes]
    const href = entry.href || definition?.href(entry.ref)
    if (!href) {
        return null
    }
    const createdById = entry.meta?.created_by
    const creator = users.find((user) => user.id === createdById) ?? null
    return {
        type,
        id: entry.ref,
        name: fileSystemEntryName(entry),
        href,
        timestamp: entry.last_viewed_at ?? entry.created_at ?? null,
        timestampLabel: entry.last_viewed_at ? 'Viewed' : 'Created',
        createdAt: entry.created_at ?? null,
        lastAccessedAt: null,
        createdBy: creator
            ? { uuid: creator.uuid, first_name: creator.first_name, last_name: creator.last_name, email: creator.email }
            : null,
        tags: [],
        spaceId: null,
        spaceName: null,
        firstBuildTaskId: null,
    }
}

// pinned: sidebar `iconType` values from the product manifests, in the order the sidebar lists them.
export const FROM_POSTHOG_ICON_TYPES = ['web_analytics', 'marketing_analytics', 'mcp_analytics'] as const

export interface FromPostHogItem {
    key: string
    label: string
    href: string
    item: FileSystemImport
}

export function isFromPostHogItem(item: Pick<FileSystemImport, 'iconType'>): boolean {
    return (FROM_POSTHOG_ICON_TYPES as readonly string[]).includes(item.iconType ?? '')
}

export function fromPostHogProducts(): FromPostHogItem[] {
    const products = getTreeItemsProducts()
    return FROM_POSTHOG_ICON_TYPES.flatMap((iconType) => {
        const item = products.find((product) => product.iconType === iconType)
        return item?.href ? [{ key: iconType, label: fileSystemEntryName(item), href: item.href, item }] : []
    })
}

export function fromPostHogItems(featureFlags: Record<string, unknown>): FromPostHogItem[] {
    return fromPostHogProducts().filter(({ item }) => !item.flag || !!featureFlags[item.flag])
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
