import { monaco } from '@monaco-editor/react'
import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DashboardTemplateType } from '~/types'
import { dashboardTemplatesLogic } from './dashboards/templates/dashboardTemplatesLogic'

import type { newDashboardTemplateLogicType } from './NewDashboardTemplateLogicType'

export const newDashboardTemplateLogic = kea<newDashboardTemplateLogicType>([
    path(['scenes', 'dashboard', 'NewDashboardTemplateLogic']),
    connect(dashboardTemplatesLogic),
    actions({
        setDashboardTemplateJSON: (dashboardTemplateJSON: string) => ({ dashboardTemplateJSON }),
        setOpenNewDashboardTemplateModal: (openNewDashboardTemplateModal: boolean) => ({
            openNewDashboardTemplateModal,
        }),
        createDashboardTemplate: (dashboardTemplateJSON: string) => ({ dashboardTemplateJSON }),
        setDashboardTemplateId: (id: string) => ({ id }),
        closeNewDashboardTemplateModal: true,
        updateValidationErrors: (markers: monaco.editor.IMarker[] | undefined) => ({ markers }),
    }),
    reducers({
        dashboardTemplateJSON: [
            '' as string,
            {
                setDashboardTemplateJSON: (_, { dashboardTemplateJSON }) => dashboardTemplateJSON,
            },
        ],
        validationError: [
            '' as string,
            {
                updateValidationErrors: (_, { markers }) => {
                    if (!markers || markers.length === 0) {
                        console.log('returning undefined')
                        return ''
                    } else {
                        console.log('updated with markers', markers)
                        return markers.map((marker) => marker.message).join(', ')
                    }
                },
            },
        ],
        isOpenNewDashboardTemplateModal: [
            false as boolean,
            {
                setOpenNewDashboardTemplateModal: (_, { openNewDashboardTemplateModal }) =>
                    openNewDashboardTemplateModal,
                closeNewDashboardTemplateModal: () => false,
            },
        ],
        id: [
            undefined as string | undefined,
            {
                setDashboardTemplateId: (_, { id }) => id,
            },
        ],
    }),
    loaders(({ values }) => ({
        dashboardTemplate: [
            null as DashboardTemplateType | null,
            {
                createDashboardTemplate: async () => {
                    const response = await api.create(
                        '/api/projects/@current/dashboard_templates',
                        JSON.parse(values.dashboardTemplateJSON)
                    )
                    lemonToast.success('Dashboard template created')
                    return response
                },
            },
        ],
        dashboardTemplateJSON: [
            '' as string,
            {
                getDashboardTemplate: async (id: string): Promise<string> => {
                    const response = await api.get(`/api/projects/@current/dashboard_templates/${id}`)
                    return JSON.stringify(response, null, 4)
                },
                updateDashboardTemplate: async (id: string): Promise<string> => {
                    const response = await api.update(
                        `/api/projects/@current/dashboard_templates/${id}`,
                        JSON.parse(values.dashboardTemplateJSON)
                    )

                    lemonToast.success('Dashboard template updated')
                    return JSON.stringify(response, null, 4)
                },
                deleteDashboardTemplate: async (id: string): Promise<string> => {
                    await api.update(`/api/projects/@current/dashboard_templates/${id}`, {
                        deleted: true,
                    })
                    lemonToast.success('Dashboard template deleted')
                    return ''
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        createDashboardTemplateSuccess: async () => {
            dashboardTemplatesLogic.actions.getAllTemplates()
        },
        updateDashboardTemplateSuccess: async () => {
            dashboardTemplatesLogic.actions.getAllTemplates()
            actions.closeNewDashboardTemplateModal()
        },
        deleteDashboardTemplateSuccess: async () => {
            dashboardTemplatesLogic.actions.getAllTemplates()
        },
    })),
])
