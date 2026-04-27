import { connect, kea, key, path, props, selectors } from 'kea'

import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'

import { dashboardsModel } from '~/models/dashboardsModel'
import { AccessControlLevel, AccessControlResourceType, DashboardBasicType, DashboardTileBasicType } from '~/types'

import type { dashboardWidgetMenusLogicType } from './dashboardWidgetMenusLogicType'
import type { DashboardWidgetPlacementDestination } from './DashboardWidgetPlacementMenu'

/** Stable key for kea; e.g. insight short_id, `text-${id}`, `button-${id}`, or `text-tile-${tileId}`. */
export interface DashboardWidgetMenusLogicProps {
    instanceKey: string
    dashboardId: number | null | undefined
    dashboards: number[] | null | undefined
    dashboard_tiles: DashboardTileBasicType[] | null | undefined
}

function canEditDestinationDashboard(d: DashboardBasicType): boolean {
    return d.user_access_level
        ? accessLevelSatisfied(AccessControlResourceType.Dashboard, d.user_access_level, AccessControlLevel.Editor)
        : true
}

/** Copy / Move dashboard submenus for insight, text, and button widgets (placement + ACL). */
export const dashboardWidgetMenusLogic = kea<dashboardWidgetMenusLogicType>([
    path(['lib', 'components', 'Cards', 'InsightCard', 'dashboardWidgetMenusLogic']),
    props({} as DashboardWidgetMenusLogicProps),
    key((props) => `${props.instanceKey}-${props.dashboardId ?? 'nd'}`),
    connect(() => ({
        values: [dashboardsModel, ['nameSortedDashboards']],
    })),
    selectors(() => ({
        /** Dashboards where this widget (insight / text / button / …) is already placed. */
        dashboardIdsWithThisWidget: [
            (_, p) => [p.dashboards, p.dashboard_tiles, p.dashboardId],
            (
                dashboards: number[] | null | undefined,
                dashboard_tiles: DashboardTileBasicType[] | null | undefined,
                dashboardId: number | null | undefined
            ): Set<number> => {
                const set = new Set<number>()
                for (const rawId of dashboards ?? []) {
                    if (rawId != null) {
                        set.add(Number(rawId))
                    }
                }
                for (const t of dashboard_tiles ?? []) {
                    if (t.dashboard_id != null) {
                        set.add(Number(t.dashboard_id))
                    }
                }
                if (dashboardId != null) {
                    set.add(Number(dashboardId))
                }
                return set
            },
        ],
        /** Destinations for Copy to and Move to submenus (disabled rows explain why a target is unavailable). */
        copyToDestinations: [
            (s, p) => [s.nameSortedDashboards, s.dashboardIdsWithThisWidget, p.dashboardId],
            (nameSortedDashboards, dashboardIdsWithThisWidget, dashboardId): DashboardWidgetPlacementDestination[] => {
                return nameSortedDashboards
                    .filter((d) => (dashboardId == null || d.id !== dashboardId) && canEditDestinationDashboard(d))
                    .map((d) => ({
                        dashboard: d,
                        disabledReason: dashboardIdsWithThisWidget.has(Number(d.id))
                            ? 'Already on this dashboard'
                            : undefined,
                    }))
            },
        ],
    })),
])
