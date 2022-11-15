import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'

import { dashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/dashboardTemplateLogic'
import { userLogic } from 'scenes/userLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { importDashboardTemplateLogicType } from './importDashboardTemplateLogicType'

export interface ImportDashboardTemplateForm {
    templateJson: any
}

const defaultFormValues: ImportDashboardTemplateForm = {
    templateJson: null,
}

export const importDashboardTemplateLogic = kea<importDashboardTemplateLogicType>([
    path(['scenes', 'dashboard', 'dashboardTemplates', 'importDashboardTemplateLogic']),
    connect({
        actions: [dashboardTemplateLogic, ['importDashboardTemplate']],
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
    forms(({ actions }) => ({
        importDashboardTemplate: {
            defaults: defaultFormValues,
            errors: (formValues) => ({
                templateJson: !formValues.templateJson ? 'the template file is required' : null,
            }),
            submit: async ({ templateJson }) => {
                if (templateJson) {
                    actions.importDashboardTemplate({ templateJson })
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        hideImportDashboardTemplateModal: () => {
            actions.resetImportDashboardTemplate()
        },
        submitImportDashboardTemplateSuccess: () => {
            actions.hideImportDashboardTemplateModal()
        },
    })),
])
