import posthog from 'posthog-js'
import { type ComponentType, type LazyExoticComponent } from 'react'

import { lazyWithRetry } from 'lib/utils/lazyWithRetry'

import type { DashboardWidgetTopHeadingProps } from '../components/WidgetCard/WidgetCardHeader'
import type { DashboardWidgetProductAccess } from '../types'
import { DASHBOARD_WIDGET_CATALOG, type DashboardWidgetCatalogKey } from '../widget_types/catalog'
import type { WidgetAvailabilityConfig } from '../widget_types/widgetAvailability'
export type DashboardWidgetTileFiltersProps = {
    tileId: number
    config: Record<string, unknown>
    onUpdateConfig?: (config: Record<string, unknown>) => void | Promise<void>
    disabledReason?: string | null
    canMutateErrorTrackingIssues?: boolean
}
import { parseActivityEventsWidgetConfigApiError } from './activity/activityEventsWidgetConfigValidation'
import type {
    WidgetIssueMetadataContext,
    WidgetIssueMetadataDelta,
} from './error_tracking/applyWidgetIssueMetadataChange'
import { parseErrorTrackingWidgetConfigApiError } from './error_tracking/errorTrackingWidgetConfigValidation'
import {
    parseExperimentResultsWidgetConfigApiError,
    parseExperimentsListWidgetConfigApiError,
} from './experiments/experimentsWidgetConfigValidation'
import { parseLogsWidgetConfigApiError } from './logs/logsWidgetConfigValidation'
import { parseSessionReplayWidgetConfigApiError } from './session_replay/sessionReplayWidgetConfigValidation'
import { parseSurveyResultsWidgetConfigApiError } from './surveys/surveysWidgetConfigValidation'

// Widget UI is code-split: the static graph keeps only config-error parsers, types, and the lazy
// factories below, so a logged-in page no longer eagerly downloads every widget's renderer, edit
// modal, and tile-filter bar. Each widget's subtree loads only when its tile actually renders.
// Rendered through <Suspense> boundaries in DashboardWidgetItem and WidgetCardHeader.
const ActivityEventsWidget = lazyWithRetry(() =>
    import('./activity/ActivityEventsWidget').then((m) => ({ default: m.ActivityEventsWidget }))
)
const ActivityEventsWidgetTileFilters = lazyWithRetry(() =>
    import('./activity/ActivityEventsWidgetTileFilters').then((m) => ({ default: m.ActivityEventsWidgetTileFilters }))
)
const EditActivityEventsWidgetModal = lazyWithRetry(() =>
    import('./activity/EditActivityEventsWidgetModal').then((m) => ({ default: m.EditActivityEventsWidgetModal }))
)
const ErrorTrackingWidget = lazyWithRetry(() =>
    import('./error_tracking/ErrorTrackingWidget').then((m) => ({ default: m.ErrorTrackingWidget }))
)
const ErrorTrackingWidgetTileFilters = lazyWithRetry(() =>
    import('./error_tracking/ErrorTrackingWidgetTileFilters').then((m) => ({
        default: m.ErrorTrackingWidgetTileFilters,
    }))
)
const EditErrorTrackingWidgetModal = lazyWithRetry(() =>
    import('./error_tracking/EditErrorTrackingWidgetModal').then((m) => ({ default: m.EditErrorTrackingWidgetModal }))
)
const ExperimentResultsWidget = lazyWithRetry(() =>
    import('./experiments/ExperimentResultsWidget').then((m) => ({ default: m.ExperimentResultsWidget }))
)
const ExperimentResultsWidgetTileFilters = lazyWithRetry(() =>
    import('./experiments/ExperimentResultsWidgetTileFilters').then((m) => ({
        default: m.ExperimentResultsWidgetTileFilters,
    }))
)
const EditExperimentResultsWidgetModal = lazyWithRetry(() =>
    import('./experiments/EditExperimentResultsWidgetModal').then((m) => ({
        default: m.EditExperimentResultsWidgetModal,
    }))
)
const ExperimentsListWidget = lazyWithRetry(() =>
    import('./experiments/ExperimentsListWidget').then((m) => ({ default: m.ExperimentsListWidget }))
)
const ExperimentsListWidgetTileFilters = lazyWithRetry(() =>
    import('./experiments/ExperimentsListWidgetTileFilters').then((m) => ({
        default: m.ExperimentsListWidgetTileFilters,
    }))
)
const EditExperimentsListWidgetModal = lazyWithRetry(() =>
    import('./experiments/EditExperimentsListWidgetModal').then((m) => ({ default: m.EditExperimentsListWidgetModal }))
)
const LogsWidget = lazyWithRetry(() => import('./logs/LogsWidget').then((m) => ({ default: m.LogsWidget })))
const LogsWidgetTileFilters = lazyWithRetry(() =>
    import('./logs/LogsWidgetTileFilters').then((m) => ({ default: m.LogsWidgetTileFilters }))
)
const EditLogsWidgetModal = lazyWithRetry(() =>
    import('./logs/EditLogsWidgetModal').then((m) => ({ default: m.EditLogsWidgetModal }))
)
const SessionReplayWidget = lazyWithRetry(() =>
    import('./session_replay/SessionReplayWidget').then((m) => ({ default: m.SessionReplayWidget }))
)
const SessionReplayWidgetTopHeading = lazyWithRetry(() =>
    import('./session_replay/SessionReplayWidget').then((m) => ({ default: m.SessionReplayWidgetTopHeading }))
)
const SessionReplayWidgetTileFilters = lazyWithRetry(() =>
    import('./session_replay/SessionReplayWidgetTileFilters').then((m) => ({
        default: m.SessionReplayWidgetTileFilters,
    }))
)
const EditSessionReplayWidgetModal = lazyWithRetry(() =>
    import('./session_replay/EditSessionReplayWidgetModal').then((m) => ({ default: m.EditSessionReplayWidgetModal }))
)
const SurveyResultsWidget = lazyWithRetry(() =>
    import('./surveys/SurveyResultsWidget').then((m) => ({ default: m.SurveyResultsWidget }))
)
const SurveyResultsWidgetTileFilters = lazyWithRetry(() =>
    import('./surveys/SurveyResultsWidgetTileFilters').then((m) => ({ default: m.SurveyResultsWidgetTileFilters }))
)
const EditSurveyResultsWidgetModal = lazyWithRetry(() =>
    import('./surveys/EditSurveyResultsWidgetModal').then((m) => ({ default: m.EditSurveyResultsWidgetModal }))
)

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

/** A widget slot reachable eagerly or via a lazy chunk — both render identically inside a <Suspense>. */
export type DashboardWidgetSlot<P> = ComponentType<P> | LazyExoticComponent<ComponentType<P>>

export type DashboardWidgetDefinition = {
    Component: DashboardWidgetSlot<DashboardWidgetComponentProps>
    TileFilters?: DashboardWidgetSlot<DashboardWidgetTileFiltersProps>
    EditModal?: DashboardWidgetSlot<DashboardWidgetEditModalProps>
    TopHeading?: DashboardWidgetSlot<DashboardWidgetTopHeadingProps>
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
    activity_events_list: {
        Component: ActivityEventsWidget,
        TileFilters: ActivityEventsWidgetTileFilters,
        EditModal: EditActivityEventsWidgetModal,
        parseConfigApiError: parseActivityEventsWidgetConfigApiError,
    },
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
        TopHeading: SessionReplayWidgetTopHeading,
        productAccess: 'session_recording',
        parseConfigApiError: parseSessionReplayWidgetConfigApiError,
    },
    experiments_list: {
        Component: ExperimentsListWidget,
        TileFilters: ExperimentsListWidgetTileFilters,
        EditModal: EditExperimentsListWidgetModal,
        productAccess: 'experiment',
        parseConfigApiError: parseExperimentsListWidgetConfigApiError,
    },
    experiment_results: {
        Component: ExperimentResultsWidget,
        TileFilters: ExperimentResultsWidgetTileFilters,
        EditModal: EditExperimentResultsWidgetModal,
        productAccess: 'experiment',
        parseConfigApiError: parseExperimentResultsWidgetConfigApiError,
    },
    survey_results: {
        Component: SurveyResultsWidget,
        TileFilters: SurveyResultsWidgetTileFilters,
        EditModal: EditSurveyResultsWidgetModal,
        productAccess: 'survey',
        parseConfigApiError: parseSurveyResultsWidgetConfigApiError,
    },
    logs_list: {
        Component: LogsWidget,
        TileFilters: LogsWidgetTileFilters,
        EditModal: EditLogsWidgetModal,
        productAccess: 'logs',
        parseConfigApiError: parseLogsWidgetConfigApiError,
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
