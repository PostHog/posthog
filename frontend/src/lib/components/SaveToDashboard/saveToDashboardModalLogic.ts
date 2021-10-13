import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { prompt } from 'lib/logic/prompt'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { saveToDashboardModalLogicType } from './saveToDashboardModalLogicType'
import { ProjectBasedLogicProps } from '../../../types'

interface SaveToDashboardModalLogicProps extends ProjectBasedLogicProps {
    fromDashboard: boolean
}

export const saveToDashboardModalLogic = kea<saveToDashboardModalLogicType<SaveToDashboardModalLogicProps>>({
    props: {} as SaveToDashboardModalLogicProps,
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
                (state, props) => dashboardsModel({ teamId: props.teamId }).selectors.lastDashboardId(state),
                (state, props) => dashboardsModel({ teamId: props.teamId }).selectors.dashboards(state),
                (_, props) => props.fromDashboard,
            ],
            (_dashboardId, lastDashboardId, dashboards, fromDashboard) =>
                _dashboardId || fromDashboard || lastDashboardId || (dashboards.length > 0 ? dashboards[0].id : null),
        ],
    },

    listeners: ({ actions, props }) => ({
        setDashboardId: ({ id }) => {
            dashboardsModel({ teamId: props.teamId }).actions.setLastDashboardId(id)
        },

        addNewDashboard: async () => {
            prompt({ key: `saveToDashboardModalLogic-new-dashboard` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: (name: string) => dashboardsModel({ teamId: props.teamId }).actions.addDashboard({ name }),
            })
        },

        [dashboardsModel({ teamId: props.teamId }).actionTypes.addDashboardSuccess]: async ({ dashboard }) => {
            eventUsageLogic.actions.reportCreatedDashboardFromModal()
            actions.setDashboardId(dashboard.id)
        },
    }),
})
