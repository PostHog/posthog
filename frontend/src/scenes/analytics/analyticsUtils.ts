import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { fileSystemTypes, getTreeItemsProducts } from '~/products'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'
import type { UserBasicType } from '~/types'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

// pinned: these values are the `type` property of the `views new picked` and `views list filtered` events.
export type AnalyticsType = 'canvas' | 'notebook' | 'dashboard' | 'insight'
export type AnalyticsTypeFilter = AnalyticsType | 'all'

export interface AnalyticsTypeInfo {
    type: AnalyticsType
    label: string
    pluralLabel: string
    description: string
    /** The product colour for an icon that has to be told one, such as an icon stack. */
    color: string
}

export const ANALYTICS_TYPES: AnalyticsTypeInfo[] = [
    {
        type: 'canvas',
        label: 'Canvas',
        pluralLabel: 'Canvases',
        description: 'A fully customizable generative page for complete control',
        color: 'var(--color-product-tasks-light)',
    },
    {
        type: 'dashboard',
        label: 'Dashboard',
        pluralLabel: 'Dashboards',
        description: 'A standardized grid with insights and widgets',
        color: 'var(--color-product-dashboards-light)',
    },
    {
        type: 'insight',
        label: 'Insight',
        pluralLabel: 'Insights',
        description: 'A chart built on your PostHog data, like a trend or a funnel, for a one-off analysis',
        color: 'var(--color-product-product-analytics-light)',
    },
    {
        type: 'notebook',
        label: 'Notebook',
        pluralLabel: 'Notebooks',
        description: 'An executable notebook for in-depth analyses and reports',
        color: 'var(--color-product-notebooks-light)',
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

export interface AnalyticsItem {
    type: AnalyticsType
    id: string
    name: string
    href: string
    /** When the item last changed, or was last viewed or created when that is all the API knows. */
    timestamp: string | null
    createdAt: string | null
    createdBy: Pick<UserBasicType, 'uuid' | 'first_name' | 'last_name' | 'email'> | null
    tags: string[]
    spaceId: string | null
    spaceName: string | null
    /** The file system row behind the item, which a drag hands to the project tree's move. */
    entry?: FileSystemEntry
}

export const ANALYTICS_BACK_NAME = 'Analytics'

/** The item's page, told where the person came from so its back control returns there rather than to the type's own list. */
export function analyticsOpenHref(item: Pick<AnalyticsItem, 'href'>, backUrl: string): string {
    return combineUrl(item.href, { backUrl, backName: ANALYTICS_BACK_NAME }).url
}

function stringTags(tags: unknown[] | undefined): string[] {
    return (tags ?? []).filter((tag): tag is string => typeof tag === 'string')
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
/** The file system folder every product files new objects under until someone moves them. */
export const UNFILED_FOLDER = 'Unfiled'

/** The folder that holds every person's own home folder. Its contents are personal, not a team space. */
export const USERS_FOLDER = 'Users'

/** A space is a top-level folder that is not the unfiled area or someone's home folder. */
export function isSpacePath(path: string): boolean {
    const segments = splitPath(path)
    return segments.length === 1 && !([UNFILED_FOLDER, USERS_FOLDER] as string[]).includes(segments[0])
}

/** The space an entry sits in: its top-level folder, or null when it is still unfiled (personal). */
export function analyticsSpaceOfPath(path: string): string | null {
    const [top] = splitPath(path)
    return top && top !== UNFILED_FOLDER && top !== USERS_FOLDER ? top : null
}

const SPACE_COLORS = [
    'var(--color-product-product-analytics-light)',
    'var(--color-product-dashboards-light)',
    'var(--color-product-notebooks-light)',
    'var(--color-product-feature-flags-light)',
    'var(--color-product-experiments-light)',
    'var(--color-product-surveys-light)',
    'var(--color-product-web-analytics-light)',
    'var(--color-product-session-replay-light)',
]

/** A stable colour for a space, from its name, so the same space looks the same everywhere. */
export function analyticsSpaceColor(name: string): string {
    let hash = 0
    for (const char of name) {
        hash = (hash * 31 + char.charCodeAt(0)) | 0
    }
    return SPACE_COLORS[Math.abs(hash) % SPACE_COLORS.length]
}

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
        timestamp: entry.created_at ?? null,
        createdAt: entry.created_at ?? null,
        createdBy: creator
            ? { uuid: creator.uuid, first_name: creator.first_name, last_name: creator.last_name, email: creator.email }
            : null,
        tags: stringTags(Array.isArray(entry.meta?.tags) ? entry.meta.tags : undefined),
        spaceId: analyticsSpaceOfPath(entry.path),
        spaceName: analyticsSpaceOfPath(entry.path),
        entry,
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
    // Product analytics has no page of its own in the manifest; its ready-made analysis is the home dashboard.
    const productAnalytics = products.find((product) => product.type === 'insight' && product.href === urls.insights())
    const home: FromPostHogItem[] = productAnalytics
        ? [
              {
                  key: 'product_analytics',
                  label: 'Product analytics',
                  href: urls.analyticsProductHome(),
                  item: {
                      ...productAnalytics,
                      iconType: 'product_analytics',
                      href: urls.analyticsProductHome(),
                      flag: FEATURE_FLAGS.TODAY_RAIL_NAV,
                  },
              },
          ]
        : []
    return [
        ...home,
        ...FROM_POSTHOG_ICON_TYPES.flatMap((iconType) => {
            const item = products.find((product) => product.iconType === iconType)
            return item?.href ? [{ key: iconType, label: fileSystemEntryName(item), href: item.href, item }] : []
        }),
    ]
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

/** Scopes the Analytics list's drag ids and drop targets apart from the project tree's own. */
export const ANALYTICS_DRAG_SCOPE = 'analytics-list'
