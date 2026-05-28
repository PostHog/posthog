import { urls } from 'scenes/urls'

import type { DashboardWidgetProductAccess } from '../types'
import { errorTrackingWidgetConfigSchema, sessionReplayWidgetConfigSchema } from './configSchemas'
import type { WidgetAvailabilityConfig } from './widgetAvailability'

export const DASHBOARD_WIDGET_HEADER_LAYOUTS = ['simple', 'dashboard_tile'] as const

export type DashboardWidgetHeaderLayout = (typeof DASHBOARD_WIDGET_HEADER_LAYOUTS)[number]

export type DashboardWidgetHeaderMeta = {
    /** Show the widget type label in the compact top heading row (e.g. "Error tracking"). */
    showWidgetType?: boolean
    /** Show the configured date range in the compact top heading row (e.g. "Last 7 days"). */
    showDateRange?: boolean
}

export type DashboardWidgetCatalogEntry = {
    /** Stable key for grouping widgets from the same product area. */
    groupId: string
    /** Product area label shown as a section heading in the add-widget modal. */
    groupLabel: string
    /** Widget variant label within the group (also used as fallback card title). */
    label: string
    description: string
    defaultConfig: Record<string, unknown>
    defaultLayout: { w: number; h: number; minW: number; minH?: number }
    productAccess?: DashboardWidgetProductAccess
    headerLayout: DashboardWidgetHeaderLayout
    headerMeta?: DashboardWidgetHeaderMeta
    /** Title shown in the card header (defaults to `label`). */
    headerTitle?: string
    /** When set, the widget title links here on private dashboard placements for users with access. */
    titleHref?: string
    /** Optional project setup requirement surfaced in widget runtime when unmet (see `widgetAvailability.ts`). */
    availability?: WidgetAvailabilityConfig
}

/** New widget types: add here. See products/dashboards/CONTRIBUTING.md. */
export const DASHBOARD_WIDGET_CATALOG = {
    error_tracking_list: {
        groupId: 'error_tracking',
        groupLabel: 'Error tracking',
        label: 'Top issues',
        description: 'Ranked list of the most impactful error tracking issues.',
        headerTitle: 'Top issues',
        defaultConfig: errorTrackingWidgetConfigSchema.parse({
            limit: 10,
            dateRange: { date_from: '-7d' },
        }),
        defaultLayout: { w: 6, h: 5, minW: 6, minH: 3 },
        productAccess: 'error_tracking',
        headerLayout: 'dashboard_tile' satisfies DashboardWidgetHeaderLayout,
        headerMeta: {
            showWidgetType: true,
            showDateRange: true,
        } satisfies DashboardWidgetHeaderMeta,
        titleHref: urls.errorTracking(),
    },
    session_replay_list: {
        groupId: 'session_replay',
        groupLabel: 'Session replay',
        label: 'Recent recordings',
        description: 'Recent session recordings you can open in the replay player.',
        headerTitle: 'Recent recordings',
        defaultConfig: sessionReplayWidgetConfigSchema.parse({
            limit: 10,
            dateRange: { date_from: '-7d' },
        }),
        defaultLayout: { w: 6, h: 5, minW: 6, minH: 3 },
        productAccess: 'session_recording',
        headerLayout: 'dashboard_tile' satisfies DashboardWidgetHeaderLayout,
        headerMeta: {
            showWidgetType: true,
            showDateRange: true,
        } satisfies DashboardWidgetHeaderMeta,
        titleHref: urls.replay(),
        availability: {
            requirement: 'session_replay_enabled',
            unavailableTitle: 'Session replay is not enabled',
            unavailableReason:
                'Turn on session recordings for this project to watch recent replays from your dashboard.',
            setupActionLabel: 'Enable session replay',
            docsHref: 'https://posthog.com/docs/session-replay',
        },
    },
} as const satisfies Record<string, DashboardWidgetCatalogEntry>

export type DashboardWidgetCatalogKey = keyof typeof DASHBOARD_WIDGET_CATALOG

/** New widget_type aliases: add here. See products/dashboards/CONTRIBUTING.md. */
export const DASHBOARD_WIDGET_TYPE_ALIASES: Partial<Record<string, DashboardWidgetCatalogKey>> = {
    error_tracking: 'error_tracking_list',
}

export function resolveDashboardWidgetCatalogKey(widgetType: string): DashboardWidgetCatalogKey | undefined {
    if (widgetType in DASHBOARD_WIDGET_CATALOG) {
        return widgetType as DashboardWidgetCatalogKey
    }
    return DASHBOARD_WIDGET_TYPE_ALIASES[widgetType]
}

export function getDashboardWidgetCatalogEntry(widgetType: string): DashboardWidgetCatalogEntry | undefined {
    const key = resolveDashboardWidgetCatalogKey(widgetType)
    return key ? DASHBOARD_WIDGET_CATALOG[key] : undefined
}
