import posthog from 'posthog-js'
import type { ComponentType } from 'react'

import type { DashboardWidgetProductAccess } from '../types'
import {
    type DashboardWidgetCatalogKey,
    DASHBOARD_WIDGET_TYPE_ALIASES,
    getDashboardWidgetCatalogEntry,
} from '../widget_types/catalog'
import type { WidgetAvailabilityConfig } from '../widget_types/widgetAvailability'

export type DashboardWidgetRegistryLookupContext = {
    tileId?: number
    dashboardId?: number
}

const reportedMissingRegistryEntries = new Set<string>()

/** Test-only: clears dedupe state so missing-registry capture can be asserted per test. */
export function resetDashboardWidgetRegistryReportingForTests(): void {
    reportedMissingRegistryEntries.clear()
}

function reportMissingDashboardWidgetRegistryEntry(
    widgetType: string,
    canonicalType: string,
    context?: DashboardWidgetRegistryLookupContext
): void {
    if (!widgetType.trim()) {
        return
    }

    const hasCatalogEntry = getDashboardWidgetCatalogEntry(widgetType) !== undefined
    const dedupeKey = `${canonicalType}:${hasCatalogEntry ? 'catalog' : 'none'}`
    if (reportedMissingRegistryEntries.has(dedupeKey)) {
        return
    }
    reportedMissingRegistryEntries.add(dedupeKey)

    const message = hasCatalogEntry
        ? 'Dashboard widget catalog entry has no matching frontend registry implementation'
        : 'Dashboard widget type has no frontend registry implementation'

    posthog.captureException(new Error(message), {
        feature: 'dashboard_widget',
        widget_type: widgetType,
        canonical_widget_type: canonicalType,
        has_catalog_entry: hasCatalogEntry,
        tile_id: context?.tileId,
        dashboard_id: context?.dashboardId,
    })
}

export type DashboardWidgetDefinition = {
    Component: ComponentType<DashboardWidgetComponentProps>
    EditModal?: ComponentType<DashboardWidgetEditModalProps>
    productAccess?: DashboardWidgetProductAccess
    /** Fallback when catalog `availability` is unmet; defaults to `WidgetAvailabilitySetupPrompt`. */
    unavailableContentFallback?: ComponentType<{ availability: WidgetAvailabilityConfig }>
}

export type DashboardWidgetComponentProps = {
    tileId: number
    config: Record<string, unknown>
    result: unknown
    loading: boolean
    error?: string | null
    onRefresh?: () => void
    onUpdateConfig?: (config: Record<string, unknown>) => void | Promise<void>
}

export type DashboardWidgetEditModalProps = {
    isOpen: boolean
    onClose: () => void
    config: Record<string, unknown>
    onSave: (config: Record<string, unknown>) => void | Promise<void>
    name?: string
    defaultTitle?: string
    description?: string
    onSaveMetadata?: (metadata: { name?: string; description?: string }) => void | Promise<void>
}

/**
 * New widget types: add here. See products/dashboards/CONTRIBUTING.md.
 *
 * `satisfies Record<DashboardWidgetCatalogKey, …>` fails typecheck if catalog grows without a matching key.
 */
export const DASHBOARD_WIDGET_REGISTRY: Record<string, DashboardWidgetDefinition> = {}

function isDashboardWidgetRegistryKey(widgetType: string): widgetType is DashboardWidgetCatalogKey {
    return widgetType in DASHBOARD_WIDGET_REGISTRY
}

export function getDashboardWidgetDefinition(
    widgetType: string,
    context?: DashboardWidgetRegistryLookupContext
): DashboardWidgetDefinition | undefined {
    const canonicalType = DASHBOARD_WIDGET_TYPE_ALIASES[widgetType] ?? widgetType
    if (!isDashboardWidgetRegistryKey(canonicalType)) {
        reportMissingDashboardWidgetRegistryEntry(widgetType, canonicalType, context)
        return undefined
    }
    return DASHBOARD_WIDGET_REGISTRY[canonicalType]
}
