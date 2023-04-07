import { connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { ExtendedListItem } from '../types'
import type { dashboardsSidebarLogicType } from './dashboardsSidebarLogicType'

export const dashboardsSidebarLogic = kea<dashboardsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'dashboardsSidebarLogic']),
    connect({
        values: [
            dashboardsModel,
            ['pinSortedDashboards', 'dashboardsLoading', 'lastDashboardId'],
            sceneLogic,
            ['activeScene'],
        ],
    }),
    selectors({
        isLoading: [(s) => [s.dashboardsLoading], (dashboardsLoading) => dashboardsLoading],
        contents: [
            (s) => [s.pinSortedDashboards],
            (pinSortedDashboards) =>
                pinSortedDashboards.map(
                    (dashboard) =>
                        ({
                            key: dashboard.id,
                            name: dashboard.name,
                            url: urls.dashboard(dashboard.id),
                            marker: dashboard.pinned ? { type: 'fold' } : undefined,
                        } as ExtendedListItem)
                ),
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.lastDashboardId],
            (activeScene, lastDashboardId) => {
                return activeScene === Scene.Dashboard ? lastDashboardId : null
            },
        ],
    }),
])
