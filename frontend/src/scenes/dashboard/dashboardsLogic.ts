import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'
import { dashboardsLogicType } from './dashboardsLogicType'
import { DashboardType, ProjectBasedLogicProps } from '~/types'
import { uniqueBy } from 'lib/utils'
import { urls } from 'scenes/urls'

export const dashboardsLogic = kea<dashboardsLogicType>({
    props: {} as ProjectBasedLogicProps,
    key: (props) => props.teamId || '',
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
    selectors: ({ props }) => ({
        dashboards: [
            () => [dashboardsModel(props).selectors.dashboards],
            (dashboards: DashboardType[]) =>
                dashboards
                    .filter((d) => !d.deleted)
                    .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')),
        ],
        dashboardTags: [
            () => [dashboardsModel(props).selectors.dashboards],
            (dashboards: DashboardType[]): string[] =>
                uniqueBy(
                    dashboards.flatMap(({ tags }) => tags),
                    (item) => item
                ).sort(),
        ],
    }),
    listeners: ({ props }) => ({
        [dashboardsModel(props).actionTypes.addDashboardSuccess]: ({ dashboard }) => {
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
