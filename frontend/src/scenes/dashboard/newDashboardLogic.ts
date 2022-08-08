import { actions, connect, kea, listeners, path, reducers } from 'kea'
import type { newDashboardLogicType } from './newDashboardLogicType'
import { DashboardRestrictionLevel } from 'lib/constants'
import { DashboardType } from '~/types'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { forms } from 'kea-forms'

export interface NewDashboardForm {
    name: string
    description: ''
    show: boolean
    useTemplate: string
    restrictionLevel: DashboardRestrictionLevel
}

const defaultFormValues: NewDashboardForm = {
    name: '',
    description: '',
    show: false,
    useTemplate: '',
    restrictionLevel: DashboardRestrictionLevel.EveryoneInProjectCanEdit,
}

export const newDashboardLogic = kea<newDashboardLogicType>([
    path(['scenes', 'dashboard', 'newDashboardLogic']),
    connect(dashboardsModel),
    actions({
        showNewDashboardModal: true,
        hideNewDashboardModal: true,
        addDashboard: (form: Partial<NewDashboardForm>) => ({ form }),
        createAndGoToDashboard: true,
    }),
    reducers({
        newDashboardModalVisible: [
            false,
            {
                showNewDashboardModal: () => true,
                hideNewDashboardModal: () => false,
            },
        ],
    }),
    forms(({ actions }) => ({
        newDashboard: {
            defaults: defaultFormValues,
            errors: ({ name, restrictionLevel }) => ({
                name: !name ? 'Please give your dashboard a name.' : null,
                restrictionLevel: !restrictionLevel ? 'Restriction level needs to be specified.' : null,
            }),
            submit: async ({ name, description, useTemplate, restrictionLevel, show }, breakpoint) => {
                const result: DashboardType = await api.create(
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/`,
                    {
                        name: name,
                        description: description,
                        use_template: useTemplate,
                        restriction_level: restrictionLevel,
                    } as Partial<DashboardType>
                )
                actions.hideNewDashboardModal()
                actions.resetNewDashboard()
                dashboardsModel.actions.addDashboardSuccess(result)
                if (show) {
                    breakpoint()
                    router.actions.push(urls.dashboard(result.id))
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        addDashboard: ({ form }) => {
            actions.resetNewDashboard()
            actions.setNewDashboardValues({ ...defaultFormValues, ...form })
            actions.submitNewDashboard()
        },
        showNewDashboardModal: () => {
            actions.resetNewDashboard()
        },
        createAndGoToDashboard: () => {
            actions.setNewDashboardValue('show', true)
            actions.submitNewDashboard()
        },
    })),
])
