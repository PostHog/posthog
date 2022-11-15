import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import type { saveDashboardTemplateLogicType } from './saveDashboardTemplateLogicType'
import { DashboardTemplateScope, dashboardTemplateScopes, DashboardType, Realm } from '~/types'
import { dashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/dashboardTemplateLogic'
import { userLogic } from 'scenes/userLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { OrganizationMembershipLevel } from 'lib/constants'

export interface SaveDashboardTemplateForm {
    dashboard: DashboardType | null
    templateName: string
    templateScope: DashboardTemplateScope
}

const defaultFormValues: SaveDashboardTemplateForm = {
    dashboard: null,
    templateName: '',
    templateScope: 'project',
}

export const saveDashboardTemplateLogic = kea<saveDashboardTemplateLogicType>([
    path(['scenes', 'dashboard', 'dashboardTemplates', 'saveDashboardTemplateLogic']),
    connect({
        actions: [dashboardTemplateLogic, ['saveDashboardTemplate']],
        values: [userLogic, ['user'], preflightLogic, ['realm', 'preflight'], teamLogic, ['currentTeam']],
    }),
    actions({
        showSaveDashboardTemplateModal: (dashboard: DashboardType) => ({ dashboard }),
        hideSaveDashboardTemplateModal: true,
    }),
    reducers({
        saveDashboardTemplateModalVisible: [
            false,
            {
                showSaveDashboardTemplateModal: () => true,
                hideSaveDashboardTemplateModal: () => false,
            },
        ],
    }),
    forms(({ actions }) => ({
        saveDashboardTemplate: {
            defaults: defaultFormValues,
            errors: (formValues) => ({
                templateName: !formValues.templateName ? 'Please enter a template name' : null,
            }),
            submit: async ({ templateName, dashboard, templateScope }) => {
                if (dashboard) {
                    actions.saveDashboardTemplate({ templateName, dashboard, templateScope })
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        showSaveDashboardTemplateModal: ({ dashboard }) => {
            actions.setSaveDashboardTemplateValues({ dashboard })
        },
        hideSaveDashboardTemplateModal: () => {
            actions.resetSaveDashboardTemplate()
        },
        submitSaveDashboardTemplateSuccess: () => {
            actions.hideSaveDashboardTemplateModal()
        },
    })),
    selectors(() => ({
        templateScopeOptions: [
            (s) => [s.user, s.realm, s.preflight, s.currentTeam],
            (user, realm, preflight, currentTeam) => {
                const showGlobalScope = (realm == Realm.Cloud || preflight?.is_debug) && user?.is_staff
                const canCreateInOrgScope =
                    currentTeam?.effective_membership_level &&
                    currentTeam?.effective_membership_level > OrganizationMembershipLevel.Member
                return dashboardTemplateScopes
                    .map((dts) => ({
                        value: dts,
                        label: dts,
                        disabled:
                            (dts === 'global' && !user?.is_staff) || (dts === 'organization' && !canCreateInOrgScope),
                    }))
                    .filter((dts) => dts.value !== 'global' || showGlobalScope)
            },
        ],
    })),
])
