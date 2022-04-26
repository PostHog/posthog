import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { prompt } from 'lib/logic/prompt'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { saveToDashboardModalLogicType } from './saveToDashboardModalLogicType'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { DashboardType, InsightModel, InsightType } from '~/types'
import Fuse from 'fuse.js'

export const saveToDashboardModalLogic = kea<saveToDashboardModalLogicType>({
    path: (key) => ['lib', 'components', 'SaveToDashboard', 'saveToDashboardModalLogic', key],
    props: {} as {
        id?: string
        insight: Partial<InsightModel>
        fromDashboard?: number
    },
    key: ({ id }) => id || 'none',
    connect: () => [newDashboardLogic, dashboardsModel, eventUsageLogic],
    actions: {
        addNewDashboard: true,
        setDashboardId: (id: number) => ({ id }),
        setSearchQuery: (query: string) => ({ query }),
        setInsight: (insight: InsightType) => ({ insight }),
    },

    reducers: {
        _dashboardId: [null as null | number, { setDashboardId: (_, { id }) => id }],
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
    },

    selectors: {
        dashboardId: [
            (s) => [
                s._dashboardId,
                dashboardsModel.selectors.lastDashboardId,
                dashboardsModel.selectors.nameSortedDashboards,
                (_, props) => props.fromDashboard,
            ],
            (_dashboardId, lastDashboardId, dashboards, fromDashboard) =>
                _dashboardId || fromDashboard || lastDashboardId || (dashboards.length > 0 ? dashboards[0].id : null),
        ],
        dashboardsFuse: [
            () => [dashboardsModel.selectors.nameSortedDashboards],
            (nameSortedDashboards) => {
                return new Fuse(nameSortedDashboards || [], {
                    keys: ['name', 'description', 'tags'],
                    threshold: 0.3,
                })
            },
        ],
        filteredDashboards: [
            (s) => [s.searchQuery, s.dashboardsFuse, dashboardsModel.selectors.nameSortedDashboards],
            (searchQuery, dashboardsFuse, nameSortedDashboards): DashboardType[] =>
                searchQuery.length
                    ? dashboardsFuse.search(searchQuery).map((r: Fuse.FuseResult<DashboardType>) => r.item)
                    : nameSortedDashboards,
        ],
        currentDashboards: [
            (s) => [s.filteredDashboards, (_, props) => props.insight],
            (filteredDashboards, insight): DashboardType[] =>
                filteredDashboards.filter((d: DashboardType) => insight.dashboards?.includes(d.id)),
        ],
        availableDashboards: [
            (s) => [s.filteredDashboards, (_, props) => props.insight],
            (filteredDashboards, insight): DashboardType[] =>
                filteredDashboards.filter((d: DashboardType) => !insight.dashboards?.includes(d.id)),
        ],
        orderedDashboards: [
            (s) => [s.currentDashboards, s.availableDashboards],
            (currentDashboards, availableDashboards): DashboardType[] => [...currentDashboards, ...availableDashboards],
        ],
    },

    listeners: ({ actions }) => ({
        setDashboardId: ({ id }) => {
            dashboardsModel.actions.setLastDashboardId(id)
        },

        addNewDashboard: async () => {
            prompt({ key: `saveToDashboardModalLogic-new-dashboard` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: (name: string) => newDashboardLogic.actions.addDashboard({ name, show: false }),
            })
        },

        [dashboardsModel.actionTypes.addDashboardSuccess]: async ({ dashboard }) => {
            eventUsageLogic.actions.reportCreatedDashboardFromModal()
            actions.setDashboardId(dashboard.id)
        },
    }),
})
