import posthog from 'posthog-js'
import type { ComponentType } from 'react'

import type { DashboardWidgetProductAccess } from '../types'
import { DASHBOARD_WIDGET_CATALOG, type DashboardWidgetCatalogKey } from '../widget_types/catalog'
import type { WidgetAvailabilityConfig } from '../widget_types/widgetAvailability'
export type DashboardWidgetTileFiltersProps = {
    tileId: number
    config: Record<string, unknown>
    onUpdateConfig?: (config: Record<string, unknown>) => void | Promise<void>
    disabledReason?: string | null
}
import type {
    WidgetIssueMetadataContext,
    WidgetIssueMetadataDelta,
} from './error_tracking/applyWidgetIssueMetadataChange'
import { EditErrorTrackingWidgetModal } from './error_tracking/EditErrorTrackingWidgetModal'
import { ErrorTrackingWidget } from './error_tracking/ErrorTrackingWidget'
import { parseErrorTrackingWidgetConfigApiError } from './error_tracking/errorTrackingWidgetConfigValidation'
import { ErrorTrackingWidgetTileFilters } from './error_tracking/ErrorTrackingWidgetTileFilters'
import { EditSessionReplayWidgetModal } from './session_replay/EditSessionReplayWidgetModal'
import { SessionReplayWidget } from './session_replay/SessionReplayWidget'
import { parseSessionReplayWidgetConfigApiError } from './session_replay/sessionReplayWidgetConfigValidation'
import { SessionReplayWidgetTileFilters } from './session_replay/SessionReplayWidgetTileFilters'

export type DashboardWidgetConfigApiErrorParser = (
    error: unknown,
    config: Record<string, unknown>
) => Record<string, string | undefined> | null

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

    const hasCatalogEntry = widgetType in DASHBOARD_WIDGET_CATALOG
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
    TileFilters?: ComponentType<DashboardWidgetTileFiltersProps>
    EditModal?: ComponentType<DashboardWidgetEditModalProps>
    productAccess?: DashboardWidgetProductAccess
    /** Maps dashboard PATCH API errors to edit-modal field errors for this widget type. */
    parseConfigApiError: DashboardWidgetConfigApiErrorParser
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
    /** Debounced run_widgets refresh after tile data changes (filters). */
    onRefreshData?: () => void
    /** Error tracking list only — optimistic row patch after status/assignee edits. */
    onApplyIssueMetadataChange?: (
        issueId: string,
        delta: WidgetIssueMetadataDelta,
        context: WidgetIssueMetadataContext
    ) => void
    /** Error tracking list only — status/assignee controls when false stay read-only. */
    canMutateErrorTrackingIssues?: boolean
    onUpdateConfig?: (config: Record<string, unknown>) => void | Promise<void>
}

export type DashboardWidgetMetadataPatch = {
    name?: string
    description?: string
}

export type DashboardWidgetEditModalProps = {
    isOpen: boolean
    onClose: () => void
    config: Record<string, unknown>
    onSave: (config: Record<string, unknown>, metadata?: DashboardWidgetMetadataPatch) => void | Promise<void>
    name?: string
    defaultTitle?: string
    description?: string
}

/**
 * New widget types: add here. See products/dashboards/CONTRIBUTING.md.
 *
 * `satisfies Record<DashboardWidgetCatalogKey, …>` fails typecheck if catalog grows without a matching key.
 */
export const DASHBOARD_WIDGET_REGISTRY = {
    error_tracking_list: {
        Component: ErrorTrackingWidget,
        TileFilters: ErrorTrackingWidgetTileFilters,
        EditModal: EditErrorTrackingWidgetModal,
        productAccess: 'error_tracking',
        parseConfigApiError: parseErrorTrackingWidgetConfigApiError,
    },
    session_replay_list: {
        Component: SessionReplayWidget,
        TileFilters: SessionReplayWidgetTileFilters,
        EditModal: EditSessionReplayWidgetModal,
        productAccess: 'session_recording',
        parseConfigApiError: parseSessionReplayWidgetConfigApiError,
    },
} satisfies Record<DashboardWidgetCatalogKey, DashboardWidgetDefinition>

function isDashboardWidgetRegistryKey(widgetType: string): widgetType is DashboardWidgetCatalogKey {
    return widgetType in DASHBOARD_WIDGET_REGISTRY
}

export function getDashboardWidgetDefinition(
    widgetType: string,
    context?: DashboardWidgetRegistryLookupContext
): DashboardWidgetDefinition | undefined {
    if (!isDashboardWidgetRegistryKey(widgetType)) {
        reportMissingDashboardWidgetRegistryEntry(widgetType, widgetType, context)
        return undefined
    }
    return DASHBOARD_WIDGET_REGISTRY[widgetType]
}

export function parseDashboardWidgetConfigApiError(
    widgetType: string,
    error: unknown,
    config: Record<string, unknown>
): Record<string, string | undefined> | null {
    return getDashboardWidgetDefinition(widgetType)?.parseConfigApiError(error, config) ?? null
}
