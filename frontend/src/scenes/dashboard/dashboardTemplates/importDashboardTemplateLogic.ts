import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'

import {
    dashboardTemplateLogic,
    pollTemplateRefreshStatus,
} from 'scenes/dashboard/dashboardTemplates/dashboardTemplateLogic'
import { userLogic } from 'scenes/userLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { importDashboardTemplateLogicType } from './importDashboardTemplateLogicType'
import { loaders } from 'kea-loaders'
import { DashboardTemplateRefresh } from '~/types'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'

export interface ImportDashboardTemplateForm {
    templateJson: File[] | null
}

const defaultFormValues: ImportDashboardTemplateForm = {
    templateJson: null,
}

export const importDashboardTemplateLogic = kea<importDashboardTemplateLogicType>([
    path(['scenes', 'dashboard', 'dashboardTemplates', 'importDashboardTemplateLogic']),
    connect({
        actions: [dashboardTemplateLogic, ['importDashboardTemplate', 'getAllDashboardTemplates']],
        values: [userLogic, ['user'], preflightLogic, ['realm', 'preflight'], teamLogic, ['currentTeam']],
    }),
    actions({
        showImportDashboardTemplateModal: true,
        hideImportDashboardTemplateModal: true,
    }),
    reducers({
        importDashboardTemplateModalVisible: [
            false,
            {
                showImportDashboardTemplateModal: () => true,
                hideImportDashboardTemplateModal: () => false,
            },
        ],
    }),
    loaders({
        dashboardTemplateRefresh: [
            null as DashboardTemplateRefresh | null,
            {
                refreshGlobalDashboardTemplate: async () => {
                    return await api.dashboardTemplates.refreshDashboardTemplatesFromRepository()
                },
            },
        ],
    }),

    forms(({ actions }) => ({
        importDashboardTemplate: {
            defaults: defaultFormValues,
            submit: async ({ templateJson }) => {
                if (templateJson?.length) {
                    actions.importDashboardTemplate({ templateJson: templateJson[0] })
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        refreshGlobalDashboardTemplateSuccess: async ({ dashboardTemplateRefresh }) => {
            if (dashboardTemplateRefresh.task_status === 'SUCCESS') {
                lemonToast.success('Templates refreshed successfully')
                actions.getAllDashboardTemplates()
                actions.hideImportDashboardTemplateModal()
            } else if (dashboardTemplateRefresh.task_status === 'PENDING') {
                await pollTemplateRefreshStatus(dashboardTemplateRefresh.task_id)
                actions.getAllDashboardTemplates()
                actions.hideImportDashboardTemplateModal()
            } else {
                lemonToast.error(`Templates refresh failed: ${dashboardTemplateRefresh.task_status}`)
            }
        },
        hideImportDashboardTemplateModal: () => {
            actions.resetImportDashboardTemplate()
        },
        submitImportDashboardTemplateSuccess: () => {
            actions.hideImportDashboardTemplateModal()
        },
    })),
])
