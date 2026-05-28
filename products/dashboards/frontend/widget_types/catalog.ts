import type { DashboardWidgetProductAccess } from '../types'
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
export const DASHBOARD_WIDGET_CATALOG = {} as const satisfies Record<string, DashboardWidgetCatalogEntry>

export type DashboardWidgetCatalogKey = keyof typeof DASHBOARD_WIDGET_CATALOG

/** New widget_type aliases: add here. See products/dashboards/CONTRIBUTING.md. */
export const DASHBOARD_WIDGET_TYPE_ALIASES: Partial<Record<string, DashboardWidgetCatalogKey>> = {}

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
