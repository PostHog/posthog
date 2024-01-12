import Fuse from 'fuse.js'
import { connect, kea, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType, DashboardType } from '~/types'
import { DashboardMode } from '~/types'

import { BasicListItem, SidebarCategory } from '../types'
import type { dashboardsSidebarLogicType } from './dashboardsType'
import { FuseSearchMatch } from './utils'

const fuse = new Fuse<DashboardType>([], {
    keys: [{ name: 'name', weight: 2 }, 'description', 'tags'],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

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
            newDashboardLogic,
            ['showNewDashboardModal'],
        ],
    }),
    selectors(({ actions }) => ({
        contents: [
            (s) => [s.relevantDashboards, s.dashboardsLoading],
            (relevantDashboards, dashboardsLoading) => [
                {
                    key: 'dashboards',
                    noun: 'dashboard',
                    loading: dashboardsLoading,
                    onAdd: () => actions.showNewDashboardModal(),
                    modalContent: <NewDashboardModal />,
                    items: relevantDashboards.map(
                        ([dashboard, matches]) =>
                            ({
                                key: dashboard.id,
                                name: dashboard.name,
                                url: urls.dashboard(dashboard.id),
                                marker: dashboard.pinned ? { type: 'fold' } : undefined,
                                searchMatch: matches
                                    ? {
                                          matchingFields: matches.map((match) => match.key),
                                          nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                                      }
                                    : null,
                                menuItems: (initiateRename) => [
                                    {
                                        items: [
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
                                                    ;(dashboard.pinned ? actions.unpinDashboard : actions.pinDashboard)(
                                                        dashboard.id,
                                                        DashboardEventSource.MoreDropdown
                                                    )
                                                },
                                                label: dashboard.pinned ? 'Unpin' : 'Pin',
                                            },
                                        ],
                                    },
                                    {
                                        items: [
                                            {
                                                onClick: initiateRename,
                                                label: 'Rename',
                                                keyboardShortcut: ['enter'],
                                            },
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
                                onRename: async (newName) => {
                                    await dashboardsModel.asyncActions.updateDashboard({
                                        id: dashboard.id,
                                        name: newName,
                                    })
                                },
                            } as BasicListItem)
                    ),
                } as SidebarCategory,
            ],
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams): [string, number] | null => {
                return activeScene === Scene.Dashboard && sceneParams.params.id
                    ? ['dashboards', parseInt(sceneParams.params.id)]
                    : null
            },
        ],
        relevantDashboards: [
            (s) => [s.pinSortedDashboards, navigation3000Logic.selectors.searchTerm],
            (pinSortedDashboards, searchTerm): [DashboardBasicType, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return fuse.search(searchTerm).map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return pinSortedDashboards.map((dashboard) => [dashboard, null])
            },
        ],
    })),
    subscriptions({
        pinSortedDashboards: (pinSortedDashboards) => {
            fuse.setCollection(pinSortedDashboards)
        },
    }),
])
