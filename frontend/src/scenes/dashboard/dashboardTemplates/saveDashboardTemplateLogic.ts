import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'

import type { saveDashboardTemplateLogicType } from './saveDashboardTemplateLogicType'
import { DashboardType } from '~/types'
import { dashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/dashboardTemplateLogic'

export interface SaveDashboardTemplateForm {
    dashboard: DashboardType | null
    templateName: string
}

const defaultFormValues: SaveDashboardTemplateForm = {
    dashboard: null,
    templateName: '',
}

export const saveDashboardTemplateLogic = kea<saveDashboardTemplateLogicType>([
    path(['scenes', 'dashboard', 'dashboardTemplates', 'saveDashboardTemplateLogic']),
    connect({ actions: [dashboardTemplateLogic, ['saveDashboardTemplate']] }),
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
    forms(() => ({
        saveDashboardTemplate: {
            defaults: defaultFormValues,
            errors: (formValues) => ({
                templateName: !formValues.templateName ? 'Please enter a template name' : null,
            }),
            submit: async ({ dashboard, templateName }) => {
                console.log('submitting', dashboard, templateName)
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
    })),
])
