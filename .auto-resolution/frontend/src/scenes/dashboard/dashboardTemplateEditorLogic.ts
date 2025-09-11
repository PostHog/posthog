import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DashboardTemplateEditorType, DashboardTemplateType, MonacoMarker } from '~/types'

import type { dashboardTemplateEditorLogicType } from './dashboardTemplateEditorLogicType'
import { dashboardTemplatesLogic } from './dashboards/templates/dashboardTemplatesLogic'

export const dashboardTemplateEditorLogic = kea<dashboardTemplateEditorLogicType>([
    path(['scenes', 'dashboard', 'dashboardTemplateEditorLogic']),
    connect(() => ({ logic: [dashboardTemplatesLogic], values: [featureFlagLogic, ['featureFlags']] })),
    actions({
        setEditorValue: (value: string) => ({ value }),
        setDashboardTemplate: (dashboardTemplate: DashboardTemplateEditorType) => ({
            dashboardTemplate,
        }),
        clear: true,
        setDashboardTemplateId: (id: string | null) => ({ id }),
        openDashboardTemplateEditor: true,
        closeDashboardTemplateEditor: true,
        updateValidationErrors: (markers: MonacoMarker[] | undefined) => ({ markers }),
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
            null as DashboardTemplateEditorType | null,
            {
                clear: () => null,
                setDashboardTemplate: (_, { dashboardTemplate }) => dashboardTemplate,
            },
        ],
        validationErrors: [
            [] as string[],
            {
                updateValidationErrors: (_, { markers }): string[] => {
                    if (!markers || markers.length === 0) {
                        return []
                    }
                    return markers.map((marker: MonacoMarker) => marker.message)
                },
                clear: () => [],
            },
        ],
        id: [
            null as string | null,
            {
                setDashboardTemplateId: (_, { id }) => id,
                clear: () => null,
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
                updateDashboardTemplate: async ({
                    id,
                    dashboardTemplateUpdates,
                }: {
                    id: string
                    dashboardTemplateUpdates?: Partial<DashboardTemplateType>
                }): Promise<DashboardTemplateEditorType | undefined> => {
                    let response = null
                    if (dashboardTemplateUpdates) {
                        response = await api.dashboardTemplates.update(id, dashboardTemplateUpdates)
                    } else if (values.dashboardTemplate) {
                        response = await api.dashboardTemplates.update(id, values.dashboardTemplate)
                    } else {
                        lemonToast.error('Unable to update dashboard template')
                        return
                    }
                    lemonToast.success('Dashboard template updated')
                    return response
                },
                deleteDashboardTemplate: async (id: string): Promise<null> => {
                    await api.dashboardTemplates.delete(id)
                    lemonToast.success('Dashboard template deleted')
                    return null
                },
            },
        ],
        templateSchema: [
            null as Record<string, any> | null,
            {
                getTemplateSchema: async (): Promise<Record<string, any>> => {
                    return await api.dashboardTemplates.getSchema()
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
        setDashboardTemplateId: ({ id }) => {
            if (id) {
                actions.getDashboardTemplate(id)
            }
        },
        getDashboardTemplateSuccess: async ({ dashboardTemplate }) => {
            if (dashboardTemplate) {
                actions.setEditorValue(JSON.stringify(dashboardTemplate))
            }
        },
        setEditorValue: async ({ value }, breakpoint) => {
            await breakpoint(500)
            if (values.validationErrors.length == 0 && value?.length) {
                try {
                    const dashboardTemplate = JSON.parse(value)
                    actions.setDashboardTemplate(dashboardTemplate)
                } catch (error) {
                    console.error('error', error)
                    lemonToast.error('Unable to parse dashboard template')
                }
            }
        },
        updateValidationErrors: async ({ markers }) => {
            // used to handle the race condition between the editor updating and the validation errors updating
            // otherwise the dashboard template might not be updated with the latest value
            if (!markers?.length) {
                actions.setEditorValue(values.editorValue)
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
