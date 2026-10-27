import posthog from 'posthog-js'

import type { Dayjs } from 'lib/dayjs'
import { now } from 'lib/dayjs'
import { DashboardEventSource, filtersForAnalytics, sanitizeInsight } from 'lib/utils/eventUsageLogic'

import { isNodeWithSource, queryUsesDataWarehouse } from '~/queries/utils'
import { DashboardMode, DashboardTile, DashboardTileSpacing, DashboardType, TileGroupDisplay } from '~/types'

export type DashboardFilterChangeType =
    | 'date'
    | 'properties'
    | 'breakdown'
    | 'variable'
    | 'interval'
    | 'test_accounts'
    | 'compare'
    | 'metric_variables'

function sanitizeTile(tile: DashboardTile | null): object | undefined {
    if (!tile) {
        return undefined
    }

    return {
        ...tile,
        insight: tile.insight ? sanitizeInsight(tile.insight) : undefined,
    }
}

export function sanitizeDashboard(dashboard: DashboardType | null): object | null {
    if (!dashboard) {
        return null
    }

    // Remove breakdown color entries, as they carry raw breakdown values (user data) — report only their count
    const { breakdown_colors, ...sanitizedDashboard } = dashboard

    return {
        ...sanitizedDashboard,
        breakdown_colors_count: breakdown_colors?.length ?? 0,
        filters: filtersForAnalytics(dashboard.filters ?? {}),
        persisted_filters: dashboard.persisted_filters ? filtersForAnalytics(dashboard.persisted_filters) : null,
        tiles: dashboard.tiles?.map((tile) => sanitizeTile(tile)) || [],
    }
}

function increment(counts: Record<string, any>, key: string): void {
    counts[key] = (counts[key] || 0) + 1
}

function insightTileCountKey(tile: DashboardTile): string {
    const query = isNodeWithSource(tile.insight?.query) ? tile.insight.query.source : tile.insight?.query
    return `${query?.kind || !!tile.text ? 'text' : 'empty'}_count`
}

function countDashboardTiles(tiles: DashboardTile[], properties: Record<string, any>): void {
    for (const tile of tiles) {
        if (tile.insight) {
            increment(properties, insightTileCountKey(tile))
            properties.sample_items_count += tile.insight.is_sample ? 1 : 0
            if (queryUsesDataWarehouse(tile.insight.query)) {
                properties.uses_data_warehouse_source = true
                properties.data_warehouse_tiles_count += 1
            }
        } else if (tile.widget) {
            increment(properties, 'widget_tiles_count')
        } else {
            increment(properties, 'text_tiles_count')
        }
    }
}

export function tileGroupProperties(
    groupDisplay: TileGroupDisplay | undefined,
    tiles: DashboardTile[]
): { group_display: TileGroupDisplay; group_count: number } {
    return {
        group_display: groupDisplay ?? 'sections',
        group_count: new Set(tiles.map((tile) => tile.group_key).filter(Boolean)).size,
    }
}

export function dashboardViewedProperties(
    dashboard: DashboardType,
    lastRefreshed: Dayjs | null,
    viewerUuid: string | undefined
): Record<string, any> {
    const { created_at, is_shared, pinned, creation_mode, id } = dashboard
    const properties: Record<string, any> = {
        created_at,
        is_shared,
        pinned,
        creation_mode,
        viewer_is_creator:
            dashboard.created_by?.uuid && viewerUuid ? dashboard.created_by.uuid === viewerUuid : undefined,
        sample_items_count: 0,
        item_count: dashboard.tiles?.length || 0,
        created_by_system: !dashboard.created_by,
        dashboard_id: id,
        ...tileGroupProperties(dashboard.customization?.group_display, dashboard.tiles || []),
        lastRefreshed: lastRefreshed?.toISOString(),
        refreshAge: lastRefreshed ? now().diff(lastRefreshed, 'seconds') : undefined,
        uses_data_warehouse_source: false,
        data_warehouse_tiles_count: 0,
    }
    countDashboardTiles(dashboard.tiles || [], properties)
    return properties
}

export function reportDashboardModeToggled(
    dashboard: DashboardType | null,
    mode: DashboardMode | null,
    source: DashboardEventSource | null,
    layoutZoom: number | null,
    layoutEditMode?: boolean
): void {
    posthog.capture('dashboard mode toggled', {
        dashboard_id: dashboard?.id,
        dashboard: sanitizeDashboard(dashboard),
        mode,
        source,
        layout_zoom: layoutZoom ?? undefined,
        layout_edit_mode: layoutEditMode ?? undefined,
    })
}

export function reportDashboardLayoutEditModeEntered(
    dashboard: DashboardType | null,
    source: DashboardEventSource,
    layoutZoom: number | null
): void {
    posthog.capture('dashboard layout edit mode entered', {
        dashboard_id: dashboard?.id,
        dashboard: sanitizeDashboard(dashboard),
        source,
        layout_zoom: layoutZoom ?? undefined,
    })
}

export function reportDashboardFiltersChanged(
    dashboard: DashboardType | null,
    changeType: DashboardFilterChangeType,
    properties: Record<string, string | number | boolean | null | undefined>
): void {
    posthog.capture('dashboard filters changed', {
        dashboard_id: dashboard?.id,
        change_type: changeType,
        ...properties,
    })
}

export function reportDashboardTileDensityConfigured(tileDensity: DashboardTileSpacing): void {
    posthog.capture('dashboard tile density configured', { tile_density: tileDensity })
}

export function reportDashboardEditModeDiscardPrompt(
    dashboard: DashboardType | null,
    action: 'shown' | 'discarded' | 'kept_editing'
): void {
    posthog.capture('dashboard edit mode discard prompt', {
        dashboard_id: dashboard?.id,
        dashboard: sanitizeDashboard(dashboard),
        action,
    })
}

export function reportDashboardMoveInitiated(method: 'single' | 'bulk', count: number): void {
    posthog.capture('dashboard move initiated', { method, count })
}

export function reportDashboardInsightDeleteAfterRemovalClicked(otherDashboardCount: number): void {
    posthog.capture('dashboard insight delete after removal clicked', {
        other_dashboard_count: otherDashboardCount,
    })
}

export function reportDashboardTileRepositioned(
    dashboardId: number,
    action: 'moved' | 'resized',
    layoutZoom: number
): void {
    posthog.capture('dashboard tile repositioned', {
        dashboard_id: dashboardId,
        action,
        layout_zoom: layoutZoom,
    })
}

export function reportDashboardInsightMetaUpdated(
    dashboardId: number | undefined,
    insightId: number,
    attribute: 'name' | 'description'
): void {
    posthog.capture('dashboard insight meta updated', {
        dashboard_id: dashboardId,
        insight_id: insightId,
        attribute,
    })
}

/** Empty-state AI prompt chips (ai-first empty dashboard only). */
export function reportDashboardEmptyAiPromptSubmitted(
    dashboardId: number | undefined,
    promptType: 'custom_prompt' | 'starter_question'
): void {
    posthog.capture('dashboard empty ai prompt submitted', {
        dashboard_id: dashboardId,
        prompt_type: promptType,
        source: 'web',
    })
}

export function reportDashboardEmptyAddChartClicked(dashboardId: number | undefined): void {
    posthog.capture('dashboard empty add chart clicked', {
        dashboard_id: dashboardId,
        source: 'web',
    })
}

export function reportDashboardEmptyWebAnalyticsClicked(dashboardId: number | undefined): void {
    posthog.capture('dashboard empty web analytics clicked', {
        dashboard_id: dashboardId,
        source: 'web',
    })
}

export function reportDashboardAddMenuOpened(source: 'header', dashboardId: number): void {
    posthog.capture('dashboard add menu opened', { source, dashboard_id: dashboardId })
}
