import { kea } from 'kea'
import Fuse from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'
import { dashboardsLogicType } from './dashboardsLogicType'
import { DashboardType } from '~/types'
import { uniqueBy } from 'lib/utils'
import { urls } from 'scenes/urls'

export enum DashboardsTab {
    All = 'all',
    Pinned = 'pinned',
    Shared = 'shared',
}

export const dashboardsLogic = kea<dashboardsLogicType<DashboardsTab>>({
    path: ['scenes', 'dashboard', 'dashboardsLogic'],
    actions: {
        addNewDashboard: true,
        setNewDashboardDrawer: (shown: boolean) => ({ shown }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setCurrentTab: (tab: DashboardsTab) => ({ tab }),
    },
    reducers: {
        newDashboardDrawer: [
            false,
            {
                setNewDashboardDrawer: (_, { shown }) => shown,
            },
        ],
        searchTerm: {
            setSearchTerm: (_, { searchTerm }) => searchTerm,
        },
        currentTab: [
            DashboardsTab.All,
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
                    dashboards.flatMap(({ tags }) => tags),
                    (item) => item
                ).sort(),
        ],
    },
    listeners: () => ({
        [dashboardsModel.actionTypes.addDashboardSuccess]: ({ dashboard }) => {
            router.actions.push(urls.dashboard(dashboard.id))
        },
    }),
    urlToAction: ({ actions }) => ({
        '/dashboard': (_: any, { new: newDashboard }) => {
            if (typeof newDashboard !== 'undefined') {
                actions.setNewDashboardDrawer(true)
            }
        },
    }),
})
