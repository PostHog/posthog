import { connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { ExtendedListItem } from '../types'
import type { dashboardsSidebarLogicType } from './dashboardsType'
import Fuse from 'fuse.js'
import { DashboardBasicType, DashboardType } from '~/types'
import { subscriptions } from 'kea-subscriptions'
import { DashboardMode } from '~/types'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'

const fuse = new Fuse<DashboardType>([], {
    keys: [{ name: 'name', weight: 2 }, 'description', 'tags'],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

export interface SearchMatch {
    indices: readonly [number, number][]
    key: string
}

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
            (s) => [s.relevantDashboards],
            (relevantDashboards) =>
                relevantDashboards.map(
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
                                await dashboardsModel.asyncActions.updateDashboard({ id: dashboard.id, name: newName })
                            },
                        } as ExtendedListItem)
                ),
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams) => {
                return activeScene === Scene.Dashboard && sceneParams.params.id ? parseInt(sceneParams.params.id) : null
            },
        ],
        relevantDashboards: [
            (s) => [s.pinSortedDashboards, navigation3000Logic.selectors.searchTerm],
            (pinSortedDashboards, searchTerm): [DashboardBasicType, SearchMatch[] | null][] => {
                if (searchTerm) {
                    return fuse.search(searchTerm).map((result) => [result.item, result.matches as SearchMatch[]])
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
