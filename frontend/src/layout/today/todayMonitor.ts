import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { isFileSystemImportShown } from 'lib/utils/fileSystemImportFlags'
import { urls } from 'scenes/urls'

import { getNavProductPages } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemImport } from '~/queries/schema/schema-general'

interface MonitorProductSpec {
    href: string
    /** A path whose pages belong to the product even though no row links to them, such as AI observability's traces. */
    section?: string
}

function monitorToolSpecs(): MonitorProductSpec[] {
    return [
        { href: urls.errorTracking() },
        { href: urls.logs() },
        { href: urls.metrics() },
        { href: urls.tracing() },
        { href: urls.uptimeMonitoring() },
    ]
}

function monitorAiProductSpecs(): MonitorProductSpec[] {
    return [
        { href: urls.aiObservabilityDashboard(), section: '/ai-observability' },
        { href: urls.aiObservabilityEvaluations(), section: '/ai-evals' },
        { href: urls.aiObservabilityPrompts(), section: '/prompt-management' },
        { href: urls.aiObservabilityClusters() },
        { href: urls.aiObservabilityPlayground() },
        { href: urls.aiObservabilityTags() },
    ]
}

export interface MonitorProduct {
    // pinned: part of the row's `data-attr`, so it keeps the product's sidebar `iconType`.
    key: string
    label: string
    href: string
    item: FileSystemImport
    matchPaths: string[]
}

export interface MonitorProducts {
    tools: MonitorProduct[]
    products: MonitorProduct[]
}

function monitorProductsFor(pages: FileSystemImport[], specs: MonitorProductSpec[]): MonitorProduct[] {
    return specs.flatMap(({ href, section }) => {
        const item = pages.find((page) => page.href === href)
        if (!item) {
            return []
        }
        const matchPaths = [href.split(/[?#]/)[0], ...(section ? [section] : [])]
        const label = item.displayLabel || splitPath(item.path).at(-1) || item.path
        return [{ key: item.iconType ?? href, label, href, item, matchPaths }]
    })
}

export function monitorProducts(): MonitorProducts {
    const pages = getNavProductPages()
    return {
        tools: monitorProductsFor(pages, monitorToolSpecs()),
        products: monitorProductsFor(pages, monitorAiProductSpecs()),
    }
}

export function monitorItems(featureFlags: FeatureFlagsSet): MonitorProducts {
    const { tools, products } = monitorProducts()
    const shown = (product: MonitorProduct): boolean => isFileSystemImportShown(product.item, featureFlags)
    return { tools: tools.filter(shown), products: products.filter(shown) }
}

export function monitorProductForPath(path: string): MonitorProduct | undefined {
    const { tools, products } = monitorProducts()
    let match: { product: MonitorProduct; matchPath: string } | undefined
    for (const product of [...tools, ...products]) {
        for (const matchPath of product.matchPaths) {
            const matches = path === matchPath || path.startsWith(`${matchPath}/`)
            if (matches && (!match || matchPath.length > match.matchPath.length)) {
                match = { product, matchPath }
            }
        }
    }
    return match?.product
}

export function isErrorTrackingIssuePath(path: string): boolean {
    return /^\/error-tracking\/[^/]+$/.test(path)
}

// pinned: shortcut `type` values. Pins are saved with them, so renaming one drops everyone's pins of that type.
export const TODAY_MONITOR_RECENT_TYPES = ['error_tracking_issue', 'logs_view', 'trace'] as const

export type TodayMonitorRecentType = (typeof TODAY_MONITOR_RECENT_TYPES)[number]

export interface TodayMonitorRecent {
    type: TodayMonitorRecentType
    name: string
    href: string
}
