import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { createElement, Fragment } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DashboardTemplateEditorType, DashboardTemplateType, MonacoMarker } from '~/types'

import { dashboardTemplatesLogic } from './dashboards/templates/dashboardTemplatesLogic'
import type { dashboardTemplateEditorLogicType } from './dashboardTemplateEditorLogicType'

/**
 * Refresh every mounted `dashboardTemplatesLogic` slice we use in-product:
 * - templates tab: `default-all-templatesTab` (via callback)
 * - new dashboard chooser: `default-all` / `feature_flag-all`
 * - dashboards page featured row: `default-featured`
 */
function refreshDashboardTemplateListsAfterMutation(templatesTabListGetAll: () => void): void {
    templatesTabListGetAll()
    dashboardTemplatesLogic.findMounted({ scope: 'default' })?.actions.getAllTemplates()
    dashboardTemplatesLogic.findMounted({ scope: 'feature_flag' })?.actions.getAllTemplates()
    dashboardTemplatesLogic
        .findMounted({ scope: 'default', listQuery: { is_featured: true } })
        ?.actions.getAllTemplates()
}

function parseDashboardTemplateEditorPayload(raw: string | undefined): DashboardTemplateEditorType | undefined {
    const trimmed = raw?.trim()
    if (!trimmed) {
        return undefined
    }
    try {
        return JSON.parse(trimmed) as DashboardTemplateEditorType
    } catch {
        return undefined
    }
}

export const dashboardTemplateEditorLogic = kea<dashboardTemplateEditorLogicType>([
    path(['scenes', 'dashboard', 'dashboardTemplateEditorLogic']),
    connect(() => ({
        actions: [dashboardTemplatesLogic({ scope: 'default', templatesTabList: true }), ['getAllTemplates']],
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setEditorValue: (value: string) => ({ value }),
        setDashboardTemplate: (dashboardTemplate: DashboardTemplateEditorType) => ({
            dashboardTemplate,
        }),
        clear: true,
        setDashboardTemplateId: (id: string | null, options?: { hydrateEditorFromApi?: boolean }) => ({
            id,
            /** When false, editor JSON was already set (e.g. metadata modal merge); avoid GET overwriting it. Default true. */
            hydrateEditorFromApi: options?.hydrateEditorFromApi ?? true,
        }),
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
    loaders(({ values, actions }) => ({
        dashboardTemplate: [
            undefined as DashboardTemplateEditorType | undefined | null,
            {
                createDashboardTemplate: async (): Promise<DashboardTemplateEditorType | undefined> => {
                    const raw = values.editorValue?.trim()
                    let payload: DashboardTemplateEditorType | undefined
                    if (raw) {
                        payload = parseDashboardTemplateEditorPayload(values.editorValue)
                        if (!payload) {
                            lemonToast.error('Unable to parse dashboard template JSON')
                            return
                        }
                    } else {
                        payload = values.dashboardTemplate ?? undefined
                    }
                    if (!payload) {
                        lemonToast.error('Unable to create dashboard template')
                        return
                    }
                    const response = await api.dashboardTemplates.create(payload)
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
                    } else {
                        const raw = values.editorValue?.trim()
                        let payload: DashboardTemplateEditorType | undefined
                        if (raw) {
                            payload = parseDashboardTemplateEditorPayload(values.editorValue)
                            if (!payload) {
                                lemonToast.error('Unable to parse dashboard template JSON')
                                return
                            }
                        } else {
                            payload = values.dashboardTemplate ?? undefined
                        }
                        if (!payload) {
                            lemonToast.error('Unable to update dashboard template')
                            return
                        }
                        response = await api.dashboardTemplates.update(id, payload)
                    }
                    lemonToast.success('Dashboard template updated')
                    return response
                },
                deleteDashboardTemplate: async ({
                    id,
                    templateName,
                }: {
                    id: string
                    templateName: string
                }): Promise<null> => {
                    try {
                        await api.dashboardTemplates.update(id, { deleted: true })
                    } catch (e: any) {
                        lemonToast.error(e?.detail || e?.message || 'Could not delete dashboard template')
                        throw e
                    }
                    const trimmedName = templateName.trim()
                    lemonToast.info(
                        trimmedName
                            ? createElement(
                                  Fragment,
                                  null,
                                  'Dashboard template ',
                                  createElement('b', null, trimmedName),
                                  ' has been deleted'
                              )
                            : 'Dashboard template has been deleted',
                        {
                            toastId: `delete-dashboard-template-${id}`,
                            button: {
                                label: 'Undo',
                                dataAttr: 'undo-dashboard-template-delete',
                                action: async () => {
                                    try {
                                        await api.dashboardTemplates.update(id, { deleted: false })
                                        refreshDashboardTemplateListsAfterMutation(actions.getAllTemplates)
                                        lemonToast.success(
                                            trimmedName
                                                ? createElement(
                                                      Fragment,
                                                      null,
                                                      'Dashboard template ',
                                                      createElement('b', null, trimmedName),
                                                      ' has been restored'
                                                  )
                                                : 'Dashboard template has been restored',
                                            { toastId: `undo-dashboard-template-${id}` }
                                        )
                                    } catch (err: any) {
                                        lemonToast.error(
                                            err?.detail || err?.message || 'Could not restore dashboard template'
                                        )
                                    }
                                },
                            },
                        }
                    )
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
            refreshDashboardTemplateListsAfterMutation(actions.getAllTemplates)
        },
        updateDashboardTemplateSuccess: async () => {
            actions.closeDashboardTemplateEditor()
            refreshDashboardTemplateListsAfterMutation(actions.getAllTemplates)
        },
        deleteDashboardTemplateSuccess: async () => {
            refreshDashboardTemplateListsAfterMutation(actions.getAllTemplates)
        },
        closeDashboardTemplateEditor: () => {
            actions.clear()
        },
        setDashboardTemplateId: ({ id, hydrateEditorFromApi }) => {
            if (id && hydrateEditorFromApi) {
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
