import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { createElement, Fragment } from 'react'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DashboardTemplateEditorType, DashboardTemplateType, MonacoMarker, NonPortableReferences } from '~/types'

import { dashboardTemplatesLogic } from './dashboards/templates/dashboardTemplatesLogic'
import type { dashboardTemplateEditorLogicType } from './dashboardTemplateEditorLogicType'

/**
 * Refresh every mounted `dashboardTemplatesLogic` slice we use in-product:
 * - templates tab: `default-all-templatesTab`
 * - new dashboard chooser: `default-all` / `feature_flag-all`
 * - dashboards page featured row: `default-featured`
 *
 * All four go through `findMounted` so we never dispatch into an unmounted instance.
 * `connect.actions` did not reliably keep the templates-tab logic mounted across the
 * editor/modal lifecycle, which surfaced as `[KEA] Can not find path … in the store.`
 * when the post-save loader read its own reducers.
 */
function refreshDashboardTemplateListsAfterMutation(): void {
    dashboardTemplatesLogic.findMounted({ scope: 'default', templatesTabList: true })?.actions.getAllTemplates()
    dashboardTemplatesLogic.findMounted({ scope: 'default' })?.actions.getAllTemplates()
    dashboardTemplatesLogic.findMounted({ scope: 'feature_flag' })?.actions.getAllTemplates()
    dashboardTemplatesLogic
        .findMounted({ scope: 'default', listQuery: { is_featured: true } })
        ?.actions.getAllTemplates()
}

/** Human-readable phrases for the project-specific references that may not resolve when sharing a template org-wide. */
function describeNonPortableReferences(refs: NonPortableReferences | null | undefined): string[] {
    const warnings: string[] = []
    if (!refs) {
        return warnings
    }
    if (refs.actions > 0) {
        warnings.push(`${refs.actions} action${refs.actions === 1 ? '' : 's'}`)
    }
    if (refs.cohorts > 0) {
        warnings.push(`${refs.cohorts} cohort${refs.cohorts === 1 ? '' : 's'}`)
    }
    if (refs.warehouse_tables.length > 0) {
        warnings.push(
            `${refs.warehouse_tables.length === 1 ? 'data warehouse table' : 'data warehouse tables'} ${refs.warehouse_tables.join(', ')}`
        )
    }
    return warnings
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
        /** Promote a team template to organization-wide, or demote it back. Confirms before either to avoid
         * accidental changes, and warns on promote when the template embeds project-specific references. */
        toggleTemplateOrganizationScope: (template: DashboardTemplateType) => ({ template }),
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
                                        refreshDashboardTemplateListsAfterMutation()
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
            refreshDashboardTemplateListsAfterMutation()
        },
        updateDashboardTemplateSuccess: async () => {
            actions.closeDashboardTemplateEditor()
            refreshDashboardTemplateListsAfterMutation()
        },
        deleteDashboardTemplateSuccess: async () => {
            refreshDashboardTemplateListsAfterMutation()
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
        toggleTemplateOrganizationScope: async ({ template }) => {
            const { id, scope } = template
            if (id === undefined) {
                console.error('Dashboard template id not defined')
                return
            }
            if (scope === 'organization') {
                LemonDialog.open({
                    title: 'Make this template visible to this project only?',
                    description:
                        'It will no longer be shared with the other projects in your organization. They will lose access to it.',
                    primaryButton: {
                        children: 'Make project-only',
                        onClick: () =>
                            actions.updateDashboardTemplate({ id, dashboardTemplateUpdates: { scope: 'team' } }),
                    },
                    secondaryButton: { children: 'Cancel' },
                })
                return
            }
            // `non_portable_references` is only computed on single-template retrieve, so fetch before warning.
            let refs: NonPortableReferences | null | undefined = template.non_portable_references
            if (!refs) {
                try {
                    refs = (await api.dashboardTemplates.get(id)).non_portable_references
                } catch {
                    refs = undefined
                }
            }
            const warnings = describeNonPortableReferences(refs)
            if (warnings.length === 0) {
                actions.updateDashboardTemplate({ id, dashboardTemplateUpdates: { scope: 'organization' } })
                return
            }
            LemonDialog.open({
                title: 'Share this template with your whole organization?',
                description: `This template references items specific to this project (${warnings.join(
                    ', '
                )}). Insights using them may show errors in other projects — events and properties work everywhere.`,
                primaryButton: {
                    children: 'Share with organization',
                    onClick: () =>
                        actions.updateDashboardTemplate({ id, dashboardTemplateUpdates: { scope: 'organization' } }),
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.getTemplateSchema()
    }),
])
