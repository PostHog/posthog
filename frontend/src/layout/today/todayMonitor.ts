import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { isFileSystemImportShown } from 'lib/utils/fileSystemImportFlags'
import { urls } from 'scenes/urls'

import { getNavProductPages, navProductHrefForPath } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { pinKey } from '~/layout/today/sidebar/sidebarPinsLogic'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'

// pinned: sidebar `iconType` values from the product manifests, in usage order.
export const MONITOR_TOOL_ICON_TYPES = ['error_tracking', 'logs', 'metrics', 'tracing', 'uptime_monitoring'] as const

// pinned: sidebar `iconType` values from the product manifests.
export const MONITOR_AI_ICON_TYPES = [
    'llm_analytics',
    'llm_evaluations',
    'llm_prompts',
    'llm_clusters',
    'llm_playground',
    'llm_tags',
] as const

// Application observability shares Tracing's icon, so these products are told apart by their page.
const MONITOR_HREF_FOR_ICON_TYPE: Partial<Record<string, () => string>> = {
    tracing: () => urls.tracing(),
}

export interface MonitorProduct {
    key: string
    label: string
    href: string
    item: FileSystemImport
}

export interface MonitorProducts {
    tools: MonitorProduct[]
    ai: MonitorProduct[]
}

function productsForIconTypes(products: FileSystemImport[], iconTypes: readonly string[]): MonitorProduct[] {
    return iconTypes.flatMap((iconType) => {
        const href = MONITOR_HREF_FOR_ICON_TYPE[iconType]?.()
        const item = products.find(
            (product) => product.iconType === iconType && !!product.href && (!href || product.href === href)
        )
        return item?.href
            ? [
                  {
                      key: iconType,
                      label: item.displayLabel || splitPath(item.path).at(-1) || item.path,
                      href: item.href,
                      item,
                  },
              ]
            : []
    })
}

export function monitorProducts(): MonitorProducts {
    const products = getNavProductPages()
    return {
        tools: productsForIconTypes(products, MONITOR_TOOL_ICON_TYPES),
        ai: productsForIconTypes(products, MONITOR_AI_ICON_TYPES),
    }
}

export function monitorItems(featureFlags: FeatureFlagsSet): MonitorProducts {
    const { tools, ai } = monitorProducts()
    const shown = (product: MonitorProduct): boolean => isFileSystemImportShown(product.item, featureFlags)
    return { tools: tools.filter(shown), ai: ai.filter(shown) }
}

let monitorHrefs: Set<string> | null = null

export function isMonitorProduct(item: Pick<FileSystemImport, 'href'>): boolean {
    if (!monitorHrefs) {
        const { tools, ai } = monitorProducts()
        monitorHrefs = new Set([...tools, ...ai].map((product) => product.href))
    }
    return !!item.href && monitorHrefs.has(item.href)
}

function firstSegment(path: string): string {
    return path.split(/[?#]/)[0].split('/')[1] ?? ''
}

/** A page no product links to, such as AI observability's traces, belongs to the first product sharing its first segment. */
export function monitorProductForPath(path: string): MonitorProduct | undefined {
    const { tools, ai } = monitorProducts()
    const products = [...tools, ...ai]
    const href = navProductHrefForPath(
        path,
        products.map((product) => product.item)
    )
    if (href) {
        return products.find((product) => product.href === href)
    }
    const segment = firstSegment(path)
    return segment ? products.find((product) => firstSegment(product.href) === segment) : undefined
}

export function isErrorTrackingIssuePath(path: string): boolean {
    return /^\/error-tracking\/[^/]+$/.test(path)
}

// pinned: shortcut `type` values. Pins are saved with them, so renaming one drops everyone's pins of that type.
const TODAY_MONITOR_RECENT_TYPES = ['error_tracking_issue', 'logs_view'] as const

export type TodayMonitorRecentType = (typeof TODAY_MONITOR_RECENT_TYPES)[number]

export interface TodayMonitorRecent {
    type: TodayMonitorRecentType
    name: string
    href: string
}

export interface TodayMonitorPin extends TodayMonitorRecent {
    key: string
}

/**
 * A scene logic that opens one issue or saved log view has a selector with this name. It gives the record as a
 * recent, or null until the record has loaded, so its name and href always belong together.
 */
export const TODAY_MONITOR_RECENT_KEY = 'todayMonitorRecent'

export function monitorRecentRowKey(href: string): string {
    return `recent:${href}`
}

function isMonitorRecentType(type: string | undefined): type is TodayMonitorRecentType {
    return (TODAY_MONITOR_RECENT_TYPES as readonly (string | undefined)[]).includes(type)
}

export function monitorPinsFromShortcuts(shortcuts: FileSystemEntry[]): TodayMonitorPin[] {
    const pins = new Map<string, TodayMonitorPin>()
    for (const shortcut of shortcuts) {
        if (!shortcut.href || !isMonitorRecentType(shortcut.type)) {
            continue
        }
        const key = pinKey(shortcut.type, shortcut.href)
        if (!pins.has(key)) {
            pins.set(key, {
                key,
                type: shortcut.type,
                name: splitPath(shortcut.path).at(-1) ?? shortcut.path,
                href: shortcut.href,
            })
        }
    }
    return [...pins.values()]
}
