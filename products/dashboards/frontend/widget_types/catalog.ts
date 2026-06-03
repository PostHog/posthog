import { urls } from 'scenes/urls'

import type { DashboardWidgetProductAccess } from '../types'
import { ErrorTrackingWidgetPreview } from '../widgets/previews/ErrorTrackingWidgetPreview'
import { SessionReplayWidgetPreview } from '../widgets/previews/SessionReplayWidgetPreview'
import { errorTrackingWidgetConfigSchema, sessionReplayWidgetConfigSchema } from './configSchemas'
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

/** Product area labels keyed by catalog `groupId`. New groups: add here. */
export const DASHBOARD_WIDGET_GROUP_LABELS = {
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
    /** Optional project setup requirement surfaced in widget runtime when unmet (see `widgetAvailability.ts`). */
    availability?: WidgetAvailabilityConfig
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
        defaultLayout: { w: 6, h: 5, minW: 6, minH: 3 },
        productAccess: 'error_tracking',
        titleHref: urls.errorTracking(),
    },
    session_replay_list: {
        groupId: 'session_replay',
        label: 'Recent recordings',
        description: 'Recent session recordings you can open in the replay player.',
        headerTitle: 'Recent recordings',
        defaultConfig: sessionReplayWidgetConfigSchema.parse({
            dateRange: { date_from: '-7d' },
        }),
        defaultLayout: { w: 6, h: 5, minW: 6, minH: 3 },
        productAccess: 'session_recording',
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

/** New widget types: add preview components here. See products/dashboards/CONTRIBUTING.md. */
export const DASHBOARD_WIDGET_PREVIEWS: Record<DashboardWidgetCatalogKey, () => JSX.Element> = {
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

export function getUnknownDashboardWidgetCatalogFallback(widgetType: string): ResolvedDashboardWidgetCatalogEntry {
    return {
        groupId: widgetType,
        label: widgetType,
        description: '',
        defaultConfig: {},
        defaultLayout: { w: 6, h: 5, minW: 6 },
        headerTitle: widgetType,
        headerLayout: DEFAULT_DASHBOARD_WIDGET_HEADER_LAYOUT,
        headerMeta: DEFAULT_DASHBOARD_WIDGET_HEADER_META,
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
    const groupOrder: string[] = []

    for (const [widgetType, entry] of Object.entries(DASHBOARD_WIDGET_CATALOG)) {
        let group = groupsById.get(entry.groupId)

        if (!group) {
            group = {
                groupId: entry.groupId,
                groupLabel: getDashboardWidgetGroupLabel(entry.groupId),
                widgets: [],
            }
            groupsById.set(entry.groupId, group)
            groupOrder.push(entry.groupId)
        }

        group.widgets.push({ widgetType: widgetType as DashboardWidgetCatalogKey, entry })
    }

    return groupOrder.map((groupId) => groupsById.get(groupId)!)
}

export const DASHBOARD_WIDGET_CATALOG_GROUPS = getDashboardWidgetCatalogGroups()
