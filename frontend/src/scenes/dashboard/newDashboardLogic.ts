import { actions, connect, isBreakpoint, kea, listeners, path, reducers } from 'kea'
import type { newDashboardLogicType } from './newDashboardLogicType'
import { DashboardRestrictionLevel } from 'lib/constants'
import { DashboardTemplateType, DashboardType } from '~/types'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { forms } from 'kea-forms'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

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
        setDashboardGroup: (group: string) => ({ group }),
        setActiveDashboardTemplate: (template: DashboardTemplateType) => ({ template }),
        clearActiveDashboardTemplate: true,
    }),
    reducers({
        newDashboardModalVisible: [
            false,
            {
                showNewDashboardModal: () => true,
                hideNewDashboardModal: () => false,
            },
        ],
        dashboardGroup: [
            undefined,
            {
                setDashboardGroup: (_, { group }) => group,
            },
        ],
        activeDashboardTemplate: [
            null as DashboardTemplateType | null,
            {
                setActiveDashboardTemplate: (_, { template }) => template,
                clearActiveDashboardTemplate: () => null,
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
                try {
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
                } catch (e: any) {
                    if (!isBreakpoint(e)) {
                        const message = e.code && e.detail ? `${e.code}: ${e.detail}` : e
                        lemonToast.error(`Could not create dashboard: ${message}`)
                    }
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
        hideNewDashboardModal: () => {
            actions.clearActiveDashboardTemplate()
            actions.resetNewDashboard()
        },
    })),
])
