import { urls } from 'scenes/urls'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import {
    activityEventsWidgetConfigSchema,
    errorTrackingWidgetConfigSchema,
    sessionReplayWidgetConfigSchema,
} from '../generated/widget-configs.zod'
import type { DashboardWidgetProductAccess } from '../types'
import { ActivityEventsWidgetPreview } from '../widgets/previews/ActivityEventsWidgetPreview'
import { ErrorTrackingWidgetPreview } from '../widgets/previews/ErrorTrackingWidgetPreview'
import { SessionReplayWidgetPreview } from '../widgets/previews/SessionReplayWidgetPreview'
import type { WidgetAvailabilityConfig } from './widgetAvailability'

export const DASHBOARD_WIDGET_HEADER_LAYOUTS = ['simple', 'dashboard_tile'] as const

export type DashboardWidgetHeaderLayout = (typeof DASHBOARD_WIDGET_HEADER_LAYOUTS)[number]

export type DashboardWidgetHeaderMeta = {
    /** Show the widget type label in the compact top heading row (e.g. "Error tracking"). Defaults to true. */
    showWidgetType?: boolean
    /** Show the configured date range in the compact top heading row (e.g. "Last 7 days"). Defaults to true. */
    showDateRange?: boolean
}

export const DEFAULT_DASHBOARD_WIDGET_HEADER_LAYOUT = 'dashboard_tile' satisfies DashboardWidgetHeaderLayout

export const DEFAULT_DASHBOARD_WIDGET_HEADER_META = {
    showWidgetType: true,
    showDateRange: true,
} satisfies DashboardWidgetHeaderMeta

/** Event properties allowed in error tracking list widget `config.widgetFilters`. */
export const ERROR_TRACKING_LIST_TILE_FILTER_PROPERTIES = [
    '$environment',
    '$current_url',
    '$pathname',
    '$team',
    '$posthog_team',
    '$temporal_worker',
    '$temporal_worker_name',
] as const

/** Event properties allowed in session replay list widget `config.widgetFilters`. */
export const SESSION_REPLAY_LIST_TILE_FILTER_PROPERTIES = [
    '$browser',
    '$os',
    '$device_type',
    '$geoip_country_code',
    '$geoip_city_name',
    '$current_url',
    '$pathname',
    '$host',
    '$referring_domain',
    '$lib',
    '$environment',
] as const

export type DashboardWidgetTileFiltersCatalogConfig = {
    quickFilterContext: QuickFilterContext
    allowedPropertyNames: readonly string[]
}

/** Product area labels keyed by catalog `groupId`. New groups: add here. */
export const DASHBOARD_WIDGET_GROUP_LABELS = {
    activity: 'Activity',
    error_tracking: 'Error tracking',
    session_replay: 'Session replay',
} as const satisfies Record<string, string>

export function getDashboardWidgetGroupLabel(groupId: string): string {
    return DASHBOARD_WIDGET_GROUP_LABELS[groupId as keyof typeof DASHBOARD_WIDGET_GROUP_LABELS] ?? groupId
}

export type DashboardWidgetCatalogEntry = {
    /** Stable key for grouping widgets from the same product area. */
    groupId: keyof typeof DASHBOARD_WIDGET_GROUP_LABELS | (string & {})
    /** Widget variant label within the group (also used as fallback card title). */
    label: string
    description: string
    defaultConfig: Record<string, unknown>
    defaultLayout: { w: number; h: number; minW: number; minH?: number }
    productAccess?: DashboardWidgetProductAccess
    headerLayout?: DashboardWidgetHeaderLayout
    headerMeta?: DashboardWidgetHeaderMeta
    /** Title shown in the card header (defaults to `label`). */
    headerTitle?: string
    /** When set, the widget title links here on private dashboard placements for users with access. */
    titleHref?: string
    /** Copy for shared/public dashboard placeholders when live widget data is not loaded. */
    sharedPlaceholder?: {
        title: string
        message: string
    }
    /** Optional project setup requirement surfaced in widget runtime when unmet (see `widgetAvailability.ts`). */
    availability?: WidgetAvailabilityConfig
    /** Quick filter context + property allowlist for on-tile filter bars. */
    tileFilters?: DashboardWidgetTileFiltersCatalogConfig
}

/** New widget types: add here. See products/dashboards/CONTRIBUTING.md. */
export const DASHBOARD_WIDGET_CATALOG = {
    error_tracking_list: {
        groupId: 'error_tracking',
        label: 'Top issues',
        description: 'Ranked list of the most impactful error tracking issues.',
        headerTitle: 'Top issues',
        defaultConfig: errorTrackingWidgetConfigSchema.parse({
            dateRange: { date_from: '-7d' },
        }),
        defaultLayout: { w: 6, h: 5, minW: 3, minH: 3 },
        productAccess: 'error_tracking',
        titleHref: urls.errorTracking(),
        sharedPlaceholder: {
            title: 'Top issues',
            message: 'Log in to PostHog to see which errors are affecting your users.',
        },
        tileFilters: {
            quickFilterContext: QuickFilterContext.ErrorTrackingIssueFilters,
            allowedPropertyNames: ERROR_TRACKING_LIST_TILE_FILTER_PROPERTIES,
        },
        availability: {
            requirement: 'exception_autocapture',
            unavailableTitle: "You haven't captured any exceptions",
            unavailableReason: 'Enable exception autocapture to get started.',
            setupActionLabel: 'Enable exception autocapture',
            docsHref: 'https://posthog.com/docs/error-tracking',
        },
    },
    session_replay_list: {
        groupId: 'session_replay',
        label: 'Recent recordings',
        description: 'Recent session recordings you can open in the replay player.',
        headerTitle: 'Recent recordings',
        defaultConfig: sessionReplayWidgetConfigSchema.parse({
            dateRange: { date_from: '-7d' },
        }),
        defaultLayout: { w: 6, h: 5, minW: 3, minH: 3 },
        productAccess: 'session_recording',
        titleHref: urls.replay(),
        sharedPlaceholder: {
            title: 'Recent recordings',
            message: 'Log in to PostHog to watch session replays from this dashboard.',
        },
        availability: {
            requirement: 'session_replay_enabled',
            unavailableTitle: 'Session replay is not enabled',
            unavailableReason:
                'Turn on session recordings for this project to watch recent replays from your dashboard.',
            setupActionLabel: 'Enable session replay',
            docsHref: 'https://posthog.com/docs/session-replay',
        },
        tileFilters: {
            quickFilterContext: QuickFilterContext.Dashboards,
            allowedPropertyNames: SESSION_REPLAY_LIST_TILE_FILTER_PROPERTIES,
        },
    },
    activity_events_list: {
        groupId: 'activity',
        label: 'Recent events',
        description: 'Latest events captured in this project, as on Activity > Explore.',
        headerTitle: 'Recent events',
        defaultConfig: activityEventsWidgetConfigSchema.parse({
            dateRange: { date_from: '-24h' },
        }),
        defaultLayout: { w: 6, h: 5, minW: 3, minH: 3 },
        titleHref: urls.activity(ActivityTab.ExploreEvents),
        sharedPlaceholder: {
            title: 'Recent events',
            message: 'Log in to PostHog to explore the latest events from this dashboard.',
        },
    },
} as const satisfies Record<string, DashboardWidgetCatalogEntry>

export type DashboardWidgetCatalogKey = keyof typeof DASHBOARD_WIDGET_CATALOG

/** New widget types: add preview components here. See products/dashboards/CONTRIBUTING.md. */
export const DASHBOARD_WIDGET_PREVIEWS: Record<DashboardWidgetCatalogKey, () => JSX.Element> = {
    activity_events_list: ActivityEventsWidgetPreview,
    error_tracking_list: ErrorTrackingWidgetPreview,
    session_replay_list: SessionReplayWidgetPreview,
}

export type ResolvedDashboardWidgetCatalogEntry = DashboardWidgetCatalogEntry & {
    headerLayout: DashboardWidgetHeaderLayout
    headerMeta: Required<DashboardWidgetHeaderMeta>
}

function resolveDashboardWidgetCatalogEntry(entry: DashboardWidgetCatalogEntry): ResolvedDashboardWidgetCatalogEntry {
    return {
        ...entry,
        headerLayout: entry.headerLayout ?? DEFAULT_DASHBOARD_WIDGET_HEADER_LAYOUT,
        headerMeta: { ...DEFAULT_DASHBOARD_WIDGET_HEADER_META, ...entry.headerMeta },
    }
}

export function getDashboardWidgetCatalogEntry(widgetType: string): ResolvedDashboardWidgetCatalogEntry {
    if (!(widgetType in DASHBOARD_WIDGET_CATALOG)) {
        throw new Error(`Unknown dashboard widget type: ${widgetType}`)
    }

    return resolveDashboardWidgetCatalogEntry(DASHBOARD_WIDGET_CATALOG[widgetType as DashboardWidgetCatalogKey])
}

export function tryGetDashboardWidgetCatalogEntry(widgetType: string): ResolvedDashboardWidgetCatalogEntry | undefined {
    if (!(widgetType in DASHBOARD_WIDGET_CATALOG)) {
        return undefined
    }

    return resolveDashboardWidgetCatalogEntry(DASHBOARD_WIDGET_CATALOG[widgetType as DashboardWidgetCatalogKey])
}

export const DEFAULT_SHARED_DASHBOARD_WIDGET_PLACEHOLDER = {
    title: 'Widget data',
    message: "Log in to PostHog to see this widget's data.",
} as const

export function getUnknownDashboardWidgetCatalogFallback(widgetType: string): ResolvedDashboardWidgetCatalogEntry {
    return {
        groupId: widgetType,
        label: widgetType,
        description: '',
        defaultConfig: {},
        defaultLayout: { w: 6, h: 5, minW: 3 },
        headerTitle: widgetType,
        headerLayout: DEFAULT_DASHBOARD_WIDGET_HEADER_LAYOUT,
        headerMeta: DEFAULT_DASHBOARD_WIDGET_HEADER_META,
        sharedPlaceholder: DEFAULT_SHARED_DASHBOARD_WIDGET_PLACEHOLDER,
    }
}

export type DashboardWidgetCatalogGroup = {
    groupId: string
    groupLabel: string
    widgets: Array<{
        widgetType: DashboardWidgetCatalogKey
        entry: DashboardWidgetCatalogEntry
    }>
}

function getDashboardWidgetCatalogGroups(): DashboardWidgetCatalogGroup[] {
    const groupsById = new Map<string, DashboardWidgetCatalogGroup>()

    for (const [widgetType, entry] of Object.entries(DASHBOARD_WIDGET_CATALOG)) {
        let group = groupsById.get(entry.groupId)

        if (!group) {
            group = {
                groupId: entry.groupId,
                groupLabel: getDashboardWidgetGroupLabel(entry.groupId),
                widgets: [],
            }
            groupsById.set(entry.groupId, group)
        }

        group.widgets.push({ widgetType: widgetType as DashboardWidgetCatalogKey, entry })
    }

    return [...groupsById.values()].sort((a, b) => a.groupLabel.localeCompare(b.groupLabel))
}

export const DASHBOARD_WIDGET_CATALOG_GROUPS = getDashboardWidgetCatalogGroups()
