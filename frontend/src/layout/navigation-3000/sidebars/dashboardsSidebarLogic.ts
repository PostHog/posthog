import { connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { ExtendedListItem } from '../types'
import type { dashboardsSidebarLogicType } from './dashboardsSidebarLogicType'
import { DashboardMode } from '~/types'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'

export const dashboardsSidebarLogic = kea<dashboardsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'dashboardsSidebarLogic']),
    connect({
        values: [
            dashboardsModel,
            ['pinSortedDashboards', 'dashboardsLoading'],
            sceneLogic,
            ['activeScene', 'sceneParams'],
        ],
        actions: [
            dashboardsModel,
            ['pinDashboard', 'unpinDashboard'],
            duplicateDashboardLogic,
            ['showDuplicateDashboardModal'],
            deleteDashboardLogic,
            ['showDeleteDashboardModal'],
        ],
    }),
    selectors(({ actions }) => ({
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
                            menuItems: [
                                {
                                    items: [
                                        {
                                            onClick: () => {
                                                ;(dashboard.pinned ? actions.unpinDashboard : actions.pinDashboard)(
                                                    dashboard.id,
                                                    DashboardEventSource.MoreDropdown
                                                )
                                            },
                                            label: dashboard.pinned ? 'Unpin' : 'Pin',
                                        },
                                        {
                                            to: urls.dashboard(dashboard.id),
                                            onClick: () => {
                                                dashboardLogic({ id: dashboard.id }).mount()
                                                dashboardLogic({ id: dashboard.id }).actions.setDashboardMode(
                                                    DashboardMode.Edit,
                                                    DashboardEventSource.DashboardsList
                                                )
                                            },
                                            label: 'Edit',
                                        },
                                        {
                                            onClick: () => {
                                                actions.showDuplicateDashboardModal(dashboard.id, dashboard.name)
                                            },
                                            label: 'Duplicate',
                                        },
                                    ],
                                },
                                {
                                    items: [
                                        {
                                            onClick: () => {
                                                actions.showDeleteDashboardModal(dashboard.id)
                                            },
                                            status: 'danger',
                                            label: 'Delete dashboard',
                                        },
                                    ],
                                },
                            ],
                        } as ExtendedListItem)
                ),
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams) => {
                return activeScene === Scene.Dashboard && sceneParams.params.id ? parseInt(sceneParams.params.id) : null
            },
        ],
    })),
])
