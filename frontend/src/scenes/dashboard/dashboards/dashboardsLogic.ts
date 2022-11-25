import { kea } from 'kea'
import Fuse from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'
import type { dashboardsLogicType } from './dashboardsLogicType'
import { DashboardType } from '~/types'
import { userLogic } from 'scenes/userLogic'
import { dashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/dashboardTemplateLogic'

export enum DashboardsTab {
    All = 'all',
    Yours = 'yours',
    Pinned = 'pinned',
    Shared = 'shared',
    Templates = 'templates',
}

export const dashboardsLogic = kea<dashboardsLogicType>({
    path: ['scenes', 'dashboard', 'dashboardsLogic'],
    connect: {
        values: [userLogic, ['user'], dashboardTemplateLogic, ['dashboardTemplates']],
        actions: [dashboardTemplateLogic, ['getAllDashboardTemplates']],
    },
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
        filteredDashboardTemplates: [
            (selectors) => [selectors.dashboardTemplates, selectors.searchTerm],
            (dashboardTemplates, searchTerm) => {
                if (!searchTerm) {
                    return dashboardTemplates
                }
                return new Fuse(dashboardTemplates, {
                    keys: ['template_name'],
                    threshold: 0.3,
                })
                    .search(searchTerm)
                    .map((result) => result.item)
            },
        ],
        dashboards: [
            (selectors) => [
                dashboardsModel.selectors.nameSortedDashboards,
                selectors.searchTerm,
                selectors.currentTab,
                selectors.user,
            ],
            (dashboards, searchTerm, currentTab, user): DashboardType[] => {
                let listToFilter: DashboardType[]

                if (currentTab === DashboardsTab.Templates) {
                    return []
                } else {
                    listToFilter = dashboards
                        .filter((d) => !d.deleted)
                        .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
                    if (currentTab === DashboardsTab.Pinned) {
                        listToFilter = dashboards.filter((d) => d.pinned)
                    } else if (currentTab === DashboardsTab.Shared) {
                        listToFilter = dashboards.filter((d) => d.is_shared)
                    } else if (currentTab === DashboardsTab.Yours) {
                        listToFilter = dashboards.filter(
                            (d) => d.created_by && user && d.created_by?.uuid === user.uuid
                        )
                    }
                }
                if (!searchTerm) {
                    return listToFilter
                }
                return new Fuse(listToFilter, {
                    keys: ['key', 'name', 'description'],
                    threshold: 0.3,
                })
                    .search(searchTerm)
                    .map((result) => result.item)
            },
        ],
    },
})
