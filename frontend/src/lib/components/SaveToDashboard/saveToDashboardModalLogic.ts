import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { prompt } from 'lib/logic/prompt'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { saveToDashboardModalLogicType } from './saveToDashboardModalLogicType'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

export const saveToDashboardModalLogic = kea<saveToDashboardModalLogicType>({
    path: (key) => ['lib', 'components', 'SaveToDashboard', 'saveToDashboardModalLogic', key],
    props: {} as {
        id?: string
        fromDashboard?: number
    },
    key: ({ id }) => id || 'none',
    connect: () => [newDashboardLogic, dashboardsModel, eventUsageLogic],
    actions: {
        addNewDashboard: true,
        setDashboardId: (id: number) => ({ id }),
    },

    reducers: {
        _dashboardId: [null as null | number, { setDashboardId: (_, { id }) => id }],
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
