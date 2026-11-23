import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { getNavProductPages } from '~/layout/panel-layout/navbar/tabs/navProductItems'

import {
    TodayPaneProduct,
    TodayPaneProductSpec,
    paneProductForPath,
    paneProductsFor,
    shownPaneProducts,
} from './todayPaneProducts'

function monitorToolSpecs(): TodayPaneProductSpec[] {
    return [
        { href: urls.errorTracking() },
        { href: urls.logs() },
        { href: urls.metrics() },
        { href: urls.tracing() },
        { href: urls.uptimeMonitoring() },
    ]
}

function monitorAiProductSpecs(): TodayPaneProductSpec[] {
    return [
        { href: urls.aiObservabilityDashboard(), section: '/ai-observability' },
        { href: urls.aiObservabilityEvaluations(), section: '/ai-evals' },
        { href: urls.aiObservabilityPrompts(), section: '/prompt-management' },
        { href: urls.aiObservabilityClusters() },
        { href: urls.aiObservabilityPlayground() },
        { href: urls.aiObservabilityTags() },
    ]
}

export interface MonitorProducts {
    tools: TodayPaneProduct[]
    products: TodayPaneProduct[]
}

export function monitorProducts(): MonitorProducts {
    const pages = getNavProductPages()
    return {
        tools: paneProductsFor(pages, monitorToolSpecs()),
        products: paneProductsFor(pages, monitorAiProductSpecs()),
    }
}

export function monitorItems(featureFlags: FeatureFlagsSet): MonitorProducts {
    const { tools, products } = monitorProducts()
    return { tools: shownPaneProducts(tools, featureFlags), products: shownPaneProducts(products, featureFlags) }
}

export function monitorProductForPath(path: string): TodayPaneProduct | undefined {
    const { tools, products } = monitorProducts()
    return paneProductForPath([...tools, ...products], path)
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
