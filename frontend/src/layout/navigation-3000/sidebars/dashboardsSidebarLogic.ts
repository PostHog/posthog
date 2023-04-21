import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { ExtendedListItem } from '../types'
import type { dashboardsSidebarLogicType } from './dashboardsSidebarLogicType'
import Fuse from 'fuse.js'
import { DashboardType } from '~/types'
import { subscriptions } from 'kea-subscriptions'

const fuse = new Fuse<DashboardType>([], {
    keys: ['name', 'description', 'tags'],
    threshold: 0.3,
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
    }),
    actions({
        setIsSearchShown: (isSearchShown: boolean) => ({ isSearchShown }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    reducers({
        isSearchShown: [
            false,
            {
                setIsSearchShown: (_, { isSearchShown }) => isSearchShown,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    selectors({
        isLoading: [(s) => [s.dashboardsLoading], (dashboardsLoading) => dashboardsLoading],
        contents: [
            (s) => [s.relevantDashboards],
            (relevantDashboards) =>
                relevantDashboards.map(
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
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams) => {
                return activeScene === Scene.Dashboard && sceneParams.params.id ? parseInt(sceneParams.params.id) : null
            },
        ],
        relevantDashboards: [
            (s) => [s.pinSortedDashboards, s.isSearchShown, s.searchTerm],
            (pinSortedDashboards, isSearchShown, searchTerm) => {
                if (isSearchShown && searchTerm) {
                    return fuse.search(searchTerm).map((result) => result.item)
                }
                return pinSortedDashboards
            },
        ],
    }),
    subscriptions({
        pinSortedDashboards: (pinSortedDashboards) => {
            fuse.setCollection(pinSortedDashboards)
        },
    }),
])
