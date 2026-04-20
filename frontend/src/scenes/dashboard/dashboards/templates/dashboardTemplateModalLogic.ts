import { actions, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { DashboardTemplateEditorType, DashboardTemplateType } from '~/types'

import type { dashboardTemplateModalLogicType } from './dashboardTemplateModalLogicType'
import { dashboardTemplatesLogic } from './dashboardTemplatesLogic'

/** Non-empty payload so Kea `ActionDefinitions` does not treat `payload.value` as `never extends true` (which forces `closeModal: true`). */
export type CloseModalActionPayload = { readonly kind: 'closeModal' }

export const dashboardTemplateModalLogic = kea<dashboardTemplateModalLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'templates', 'dashboardTemplateModalLogic']),
    connect(() => ({
        actions: [dashboardTemplatesLogic({ scope: 'default', templatesTabList: true }), ['getAllTemplates']],
    })),
    actions({
        openCreate: (payload: DashboardTemplateEditorType) => ({ payload }),
        openEdit: (template: DashboardTemplateType) => ({ template }),
        closeModal: (): CloseModalActionPayload => ({ kind: 'closeModal' }),
        setTemplateName: (name: string) => ({ name }),
        setDashboardDescription: (dashboardDescription: string) => ({ dashboardDescription }),
        setTemplateTags: (templateTags: string[]) => ({ templateTags }),
    }),
    reducers({
        isOpen: [
            false,
            {
                openCreate: () => true,
                openEdit: () => true,
                closeModal: () => false,
            },
        ],
        mode: [
            'create' as 'create' | 'edit',
            {
                openCreate: () => 'create',
                openEdit: () => 'edit',
            },
        ],
        createPayload: [
            null as DashboardTemplateEditorType | null,
            {
                openCreate: (_, { payload }) => payload,
                closeModal: () => null,
            },
        ],
        editingTemplate: [
            null as DashboardTemplateType | null,
            {
                openEdit: (_, { template }) => template,
                closeModal: () => null,
            },
        ],
        templateName: [
            '',
            {
                openCreate: (_, { payload }) => payload.template_name || '',
                openEdit: (_, { template }) => template.template_name || '',
                closeModal: () => '',
                setTemplateName: (_, { name }) => name,
            },
        ],
        dashboardDescription: [
            '',
            {
                openCreate: (_, { payload }) => payload.dashboard_description || '',
                openEdit: (_, { template }) => template.dashboard_description || '',
                closeModal: () => '',
                setDashboardDescription: (_, { dashboardDescription }) => dashboardDescription,
            },
        ],
        templateTags: [
            [] as string[],
            {
                openCreate: (_, { payload }) => [...(payload.tags || [])],
                openEdit: (_, { template }) => [...(template.tags || [])],
                closeModal: () => [],
                setTemplateTags: (_, { templateTags }) => templateTags,
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        projectTemplateSave: [
            null as boolean | null,
            {
                saveProjectTemplate: async () => {
                    const tags = values.templateTags.map((t) => t.trim()).filter(Boolean)
                    if (!values.templateName.trim()) {
                        lemonToast.error('Enter a template name')
                        return null
                    }
                    try {
                        if (values.mode === 'create') {
                            if (!values.createPayload) {
                                lemonToast.error('Missing template payload')
                                return null
                            }
                            const data: DashboardTemplateEditorType = {
                                ...values.createPayload,
                                template_name: values.templateName.trim(),
                                dashboard_description: values.dashboardDescription,
                                tags,
                            }
                            await api.dashboardTemplates.create(data)
                            lemonToast.success('Project template saved')
                        } else {
                            const id = values.editingTemplate?.id
                            if (id === undefined) {
                                lemonToast.error('Missing template')
                                return null
                            }
                            await api.dashboardTemplates.update(id, {
                                template_name: values.templateName.trim(),
                                dashboard_description: values.dashboardDescription,
                                tags,
                            })
                            lemonToast.success('Template updated')
                        }
                        actions.getAllTemplates()
                        actions.closeModal()
                        return true
                    } catch (e: any) {
                        const msg =
                            e?.detail ||
                            e?.message ||
                            (typeof e === 'string' ? e : 'Could not save the dashboard template')
                        lemonToast.error(msg)
                        return null
                    }
                },
            },
        ],
    })),
])
