import { kea } from 'kea'
import Fuse from 'fuse.js'
import { dashboardsModel } from '~/models/dashboardsModel'
import type { dashboardsLogicType } from './dashboardsLogicType'
import { DashboardTemplateListing, DashboardType } from '~/types'
import { uniqueBy } from 'lib/utils'
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
        dashboards: [
            (selectors) => [
                dashboardsModel.selectors.nameSortedDashboards,
                selectors.searchTerm,
                selectors.currentTab,
                selectors.user,
                selectors.dashboardTemplates,
            ],
            (
                dashboards,
                searchTerm,
                currentTab,
                user,
                dashboardTemplates
            ): DashboardType[] | DashboardTemplateListing[] => {
                let listToFilter: DashboardType[] | DashboardTemplateListing[]

                if (currentTab === DashboardsTab.Templates) {
                    listToFilter = dashboardTemplates
                } else {
                    listToFilter = dashboards
                        .filter((d) => !d.deleted)
                        .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'))
                    if (currentTab === DashboardsTab.Pinned) {
                        dashboards = dashboards.filter((d) => d.pinned)
                    } else if (currentTab === DashboardsTab.Shared) {
                        dashboards = dashboards.filter((d) => d.is_shared)
                    } else if (currentTab === DashboardsTab.Yours) {
                        dashboards = dashboards.filter((d) => d.created_by && user && d.created_by?.uuid === user.uuid)
                    }
                }
                if (!searchTerm) {
                    return listToFilter
                }
                return new Fuse(dashboards, {
                    keys: ['key', 'name', 'template_name', 'description'],
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
