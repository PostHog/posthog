import { kea } from 'kea'
import type { newDashboardFormType } from './newDashboardFormType'
import { DashboardRestrictionLevel } from 'lib/constants'
import { DashboardType } from '~/types'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'

export interface NewDashboardForm {
    name: string
    show: boolean
    useTemplate: string
    restrictionLevel: DashboardRestrictionLevel
}

const defaultFormValues: NewDashboardForm = {
    name: '',
    show: true,
    useTemplate: '',
    restrictionLevel: DashboardRestrictionLevel.EveryoneInProjectCanEdit,
}

export const newDashboardForm = kea<newDashboardFormType<NewDashboardForm>>({
    path: ['scenes', 'dashboard', 'newDashboardForm'],
    connect: () => [dashboardsModel],
    actions: {
        showNewDashboardModal: true,
        hideNewDashboardModal: true,
        addDashboard: (form: Partial<NewDashboardForm>) => ({ form }),
    },
    reducers: {
        newDashboardModalVisible: [
            false,
            {
                showNewDashboardModal: () => true,
                hideNewDashboardModal: () => false,
            },
        ],
    },
    forms: ({ actions }) => ({
        newDashboard: {
            defaults: defaultFormValues,
            validator: ({ name, restrictionLevel }) => ({
                name: !name ? 'Please give your dashboard a name.' : null,
                restrictionLevel: !restrictionLevel ? 'Restriction level needs to be specified.' : null,
            }),
            submit: async ({ name, useTemplate, restrictionLevel, show }, breakpoint) => {
                const result: DashboardType = await api.create(
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/`,
                    {
                        name: name,
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
    }),
    listeners: ({ actions }) => ({
        addDashboard: ({ form }) => {
            actions.resetNewDashboard()
            actions.setNewDashboardValues({ ...defaultFormValues, ...form })
            actions.submitNewDashboard()
        },
        showNewDashboardModal: () => {
            actions.resetNewDashboard()
        },
    }),
})
