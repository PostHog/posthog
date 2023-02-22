import { editor } from 'monaco-editor'
import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DashboardTemplateEditorType, DashboardTemplateType } from '~/types'
import { dashboardTemplatesLogic } from './dashboards/templates/dashboardTemplatesLogic'

import type { dashboardTemplateEditorLogicType } from './DashboardTemplateEditorLogicType'

export const dashboardTemplateEditorLogic = kea<dashboardTemplateEditorLogicType>([
    path(['scenes', 'dashboard', 'DashboardTemplateEditorLogic']),
    connect(dashboardTemplatesLogic),
    actions({
        setEditorValue: (value: string) => ({ value }),
        setDashboardTemplate: (dashboardTemplate: DashboardTemplateEditorType) => ({
            dashboardTemplate,
        }),
        clear: true,
        setDashboardTemplateId: (id: string | undefined) => ({ id }),
        openDashboardTemplateEditor: true,
        closeDashboardTemplateEditor: true,
        updateValidationErrors: (markers: editor.IMarker[] | undefined) => ({ markers }),
    }),
    reducers({
        editorValue: [
            '' as string,
            {
                setEditorValue: (_, { value }) => value,
                clear: () => '',
            },
        ],
        dashboardTemplate: [
            undefined as DashboardTemplateEditorType | undefined,
            {
                clear: () => undefined,
                setDashboardTemplate: (_, { dashboardTemplate }) => dashboardTemplate,
            },
        ],
        validationErrors: [
            [] as string[],
            {
                updateValidationErrors: (_, { markers }): string[] => {
                    if (!markers || markers.length === 0) {
                        console.log('returning undefined')
                        return []
                    } else {
                        console.log('updated with markers', markers)
                        return markers.map((marker: editor.IMarker) => marker.message)
                    }
                },
                clear: () => [],
            },
        ],
        id: [
            undefined as string | undefined,
            {
                setDashboardTemplateId: (_, { id }) => id,
                clear: () => undefined,
            },
        ],
        isOpenNewDashboardTemplateModal: [
            false as boolean,
            {
                openDashboardTemplateEditor: () => true,
                closeDashboardTemplateEditor: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        dashboardTemplate: [
            undefined as DashboardTemplateEditorType | undefined | null,
            {
                createDashboardTemplate: async (): Promise<DashboardTemplateEditorType | undefined> => {
                    if (!values.dashboardTemplate) {
                        lemonToast.error('Unable to create dashboard template')
                        return
                    }
                    const response = await api.dashboardTemplates.create(values.dashboardTemplate)
                    lemonToast.success('Dashboard template created')
                    return response
                },
                getDashboardTemplate: async (id: string): Promise<DashboardTemplateType> => {
                    const response = await api.dashboardTemplates.get(id)
                    return response
                },
                updateDashboardTemplate: async (id: string): Promise<DashboardTemplateType | undefined> => {
                    if (!values.dashboardTemplate) {
                        lemonToast.error('Unable to update dashboard template')
                        return
                    }
                    const response = await api.dashboardTemplates.update(id, values.dashboardTemplate)
                    lemonToast.success('Dashboard template updated')
                    return response
                },
                deleteDashboardTemplate: async (id: string): Promise<null> => {
                    await api.dashboardTemplates.delete(id)
                    lemonToast.success('Dashboard template deleted')
                    return null // for some reason this errors when it's undefined instead
                },
            },
        ],
        templateSchema: [
            undefined as Record<string, any> | undefined,
            {
                getTemplateSchema: async (): Promise<Record<string, any>> => {
                    debugger
                    const response = await api.dashboardTemplates.getSchema()
                    return response
                },
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        createDashboardTemplateSuccess: async () => {
            actions.closeDashboardTemplateEditor()
            dashboardTemplatesLogic.actions.getAllTemplates()
        },
        updateDashboardTemplateSuccess: async () => {
            actions.closeDashboardTemplateEditor()
            dashboardTemplatesLogic.actions.getAllTemplates()
        },
        deleteDashboardTemplateSuccess: async () => {
            dashboardTemplatesLogic.actions.getAllTemplates()
        },
        closeDashboardTemplateEditor: () => {
            actions.clear()
        },
        setDashboardTemplateId: async ({ id }) => {
            if (id) {
                await actions.getDashboardTemplate(id)
            }
        },
        getDashboardTemplateSuccess: async ({ dashboardTemplate }) => {
            if (dashboardTemplate) {
                actions.setEditorValue(JSON.stringify(dashboardTemplate))
            }
        },
        setEditorValue: async ({ value }, breakdpoint) => {
            await breakdpoint(500)
            if (values.validationErrors.length == 0 && value?.length) {
                try {
                    const dashboardTemplate = JSON.parse(value)
                    actions.setDashboardTemplate(dashboardTemplate)
                } catch (error) {
                    console.log('error', error)
                    lemonToast.error('Unable to parse dashboard template')
                }
            }
        },
        setDashboardTemplate: async ({ dashboardTemplate }) => {
            if (dashboardTemplate) {
                actions.setEditorValue(JSON.stringify(dashboardTemplate, null, 4))
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.getTemplateSchema()
    }),
])
