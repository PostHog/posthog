import { kea } from 'kea'
import Fuse from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'
import type { dashboardsLogicType } from './dashboardsLogicType'
import { DashboardType } from '~/types'
import { uniqueBy } from 'lib/utils'

export enum DashboardsTab {
    All = 'all',
    Pinned = 'pinned',
    Shared = 'shared',
}

export const dashboardsLogic = kea<dashboardsLogicType>({
    path: ['scenes', 'dashboard', 'dashboardsLogic'],
    actions: {
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setCurrentTab: (tab: DashboardsTab) => ({ tab }),
    },
    reducers: {
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        currentTab: [
            DashboardsTab.All as DashboardsTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    },
    selectors: {
        dashboards: [
            (selectors) => [dashboardsModel.selectors.nameSortedDashboards, selectors.searchTerm, selectors.currentTab],
            (dashboards, searchTerm, currentTab) => {
                dashboards = dashboards
                    .filter((d) => !d.deleted)
                    .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
                if (currentTab === DashboardsTab.Pinned) {
                    dashboards = dashboards.filter((d) => d.pinned)
                } else if (currentTab === DashboardsTab.Shared) {
                    dashboards = dashboards.filter((d) => d.is_shared)
                }
                if (!searchTerm) {
                    return dashboards
                }
                return new Fuse(dashboards, {
                    keys: ['key', 'name'],
                    threshold: 0.3,
                })
                    .search(searchTerm)
                    .map((result) => result.item)
            },
        ],
        dashboardTags: [
            () => [dashboardsModel.selectors.nameSortedDashboards],
            (dashboards: DashboardType[]): string[] =>
                uniqueBy(
                    dashboards.flatMap(({ tags }) => tags || ''),
                    (item) => item
                ).sort(),
        ],
    },
})
