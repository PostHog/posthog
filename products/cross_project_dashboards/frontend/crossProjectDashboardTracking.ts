import posthog from 'posthog-js'

import type { TileUnavailableReason } from './crossProjectTileFetch'

// pinned: event names and property keys. Usage dashboards and funnels query them, so a rename breaks them.
const EVENTS = {
    viewed: 'cross project dashboard viewed',
    created: 'cross project dashboard created',
    deleted: 'cross project dashboard deleted',
    edited: 'cross project dashboard edited',
    addInsightOpened: 'cross project dashboard add insight opened',
    insightAdded: 'cross project dashboard insight added',
    insightAddFailed: 'cross project dashboard insight add failed',
    tileRemoved: 'cross project dashboard tile removed',
    tileRestored: 'cross project dashboard tile restored',
    tileUnavailable: 'cross project dashboard tile unavailable',
} as const

export type CrossProjectDashboardChange =
    | 'name'
    | 'description'
    | 'date_range'
    | 'interval'
    | 'property_filter'
    | 'layout'
    | 'tile_color'
    | 'tile_filters'

export type CrossProjectDashboardDeleteSource = 'dashboard' | 'list'

interface TileReference {
    project_id: number
}

/** A dashboard with tiles from two or more projects is the one the feature exists for. */
function composition(tiles: readonly TileReference[]): { tile_count: number; project_count: number } {
    return { tile_count: tiles.length, project_count: new Set(tiles.map((tile) => tile.project_id)).size }
}

export const crossProjectDashboardTracking = {
    viewed: (dashboardId: string, tiles: readonly TileReference[]): void => {
        posthog.capture(EVENTS.viewed, { dashboard_id: dashboardId, ...composition(tiles) })
    },
    created: (dashboardId: string): void => {
        posthog.capture(EVENTS.created, { dashboard_id: dashboardId })
    },
    deleted: (dashboardId: string, source: CrossProjectDashboardDeleteSource): void => {
        posthog.capture(EVENTS.deleted, { dashboard_id: dashboardId, source })
    },
    edited: (dashboardId: string, change: CrossProjectDashboardChange): void => {
        posthog.capture(EVENTS.edited, { dashboard_id: dashboardId, change })
    },
    addInsightOpened: (dashboardId: string, tiles: readonly TileReference[]): void => {
        posthog.capture(EVENTS.addInsightOpened, { dashboard_id: dashboardId, ...composition(tiles) })
    },
    /** `tiles` is the dashboard after the add, so the counts include the new tile. */
    insightAdded: (dashboardId: string, tiles: readonly TileReference[], usedSearch: boolean): void => {
        posthog.capture(EVENTS.insightAdded, {
            dashboard_id: dashboardId,
            ...composition(tiles),
            used_search: usedSearch,
        })
    },
    insightAddFailed: (dashboardId: string, status: number | undefined): void => {
        posthog.capture(EVENTS.insightAddFailed, { dashboard_id: dashboardId, status: status ?? null })
    },
    tileRemoved: (dashboardId: string): void => {
        posthog.capture(EVENTS.tileRemoved, { dashboard_id: dashboardId })
    },
    tileRestored: (dashboardId: string): void => {
        posthog.capture(EVENTS.tileRestored, { dashboard_id: dashboardId })
    },
    tileUnavailable: (reason: TileUnavailableReason): void => {
        posthog.capture(EVENTS.tileUnavailable, { reason })
    },
}
