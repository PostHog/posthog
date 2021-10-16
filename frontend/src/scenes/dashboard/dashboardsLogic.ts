import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'
import { dashboardsLogicType } from './dashboardsLogicType'
import { DashboardType } from '~/types'
import { uniqueBy } from 'lib/utils'
import { urls } from 'scenes/urls'

export const dashboardsLogic = kea<dashboardsLogicType>({
    actions: {
        addNewDashboard: true,
        setNewDashboardDrawer: (shown: boolean) => ({ shown }),
    },
    reducers: {
        newDashboardDrawer: [
            false,
            {
                setNewDashboardDrawer: (_, { shown }) => shown,
            },
        ],
    },
    selectors: {
        dashboards: [
            () => [dashboardsModel.selectors.nameSortedDashboards],
            (dashboards: DashboardType[]) =>
                dashboards
                    .filter((d) => !d.deleted)
                    .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')),
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
