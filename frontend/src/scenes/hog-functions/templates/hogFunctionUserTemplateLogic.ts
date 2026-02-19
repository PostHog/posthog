import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { HogFunctionConfigurationType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'
import { hogFunctionTemplateListLogic } from '../list/hogFunctionTemplateListLogic'
import type { hogFunctionUserTemplateLogicType } from './hogFunctionUserTemplateLogicType'

export interface HogFunctionUserTemplateLogicProps {
    id: string
    editUserTemplateId?: string
}

export const hogFunctionUserTemplateLogic = kea<hogFunctionUserTemplateLogicType>([
    path(['scenes', 'hog-functions', 'templates', 'hogFunctionUserTemplateLogic']),
    props({} as HogFunctionUserTemplateLogicProps),
    key((props) => `${props.id}-${props.editUserTemplateId || ''}`),
    actions({
        showSaveAsTemplateModal: (configuration: HogFunctionConfigurationType) => ({ configuration }),
        hideSaveAsTemplateModal: true,
    }),
    reducers({
        saveAsTemplateModalVisible: [
            false,
            {
                showSaveAsTemplateModal: () => true,
                hideSaveAsTemplateModal: () => false,
                submitTemplateFormSuccess: () => false,
            },
        ],
        currentConfiguration: [
            null as HogFunctionConfigurationType | null,
            {
                showSaveAsTemplateModal: (_, { configuration }) => configuration,
            },
        ],
    }),
    selectors({
        isEditMode: [
            () => [(_, props: HogFunctionUserTemplateLogicProps) => props],
            (props: HogFunctionUserTemplateLogicProps): boolean => !!props.editUserTemplateId,
        ],
    }),
    forms(({ actions, values, props }) => ({
        templateForm: {
            defaults: {
                name: '',
                description: '',
                tags: [] as string[],
                scope: 'team' as 'team' | 'organization',
            },
            errors: ({ name }: { name: string }) => ({
                name: !name ? 'Name is required' : undefined,
            }),
            submit: async (formValues: {
                name: string
                description: string
                tags: string[]
                scope: 'team' | 'organization'
            }) => {
                const configuration = values.currentConfiguration
                if (!configuration) {
                    return
                }

                if (props.editUserTemplateId) {
                    try {
                        const { bytecode, bytecode_error, ...cleanFilters } = configuration.filters ?? {}
                        await api.hogFunctionUserTemplates.update(props.editUserTemplateId, {
                            name: formValues.name || configuration.name || '',
                            description: formValues.description || configuration.description || '',
                            icon_url: configuration.icon_url,
                            type: configuration.type || 'transformation',
                            hog: configuration.hog || '',
                            inputs_schema: configuration.inputs_schema || [],
                            inputs: configuration.inputs,
                            filters: configuration.filters ? cleanFilters : undefined,
                            mappings: configuration.mappings,
                            masking: configuration.masking,
                            tags: formValues.tags,
                            scope: formValues.scope,
                        })
                        lemonToast.success('Template updated')
                        actions.hideSaveAsTemplateModal()
                        // Reload the template in the configuration logic so the form resets to the saved state
                        const configLogic = hogFunctionConfigurationLogic.findMounted({
                            id: 'new',
                            editUserTemplateId: props.editUserTemplateId,
                        })
                        configLogic?.actions.loadTemplate()
                    } catch (e: any) {
                        lemonToast.error(e?.detail || e?.message || 'Failed to update template')
                        throw e
                    }
                    return
                }

                try {
                    await api.hogFunctionUserTemplates.createFromFunction({
                        hog_function_id: props.id,
                        name: formValues.name,
                        description: formValues.description,
                        scope: formValues.scope,
                        tags: formValues.tags,
                    })
                    lemonToast.success('Template created')
                    actions.hideSaveAsTemplateModal()

                    const templatesLogic = hogFunctionTemplateListLogic.findMounted({
                        type: 'transformation',
                    })
                    if (templatesLogic) {
                        templatesLogic.actions.loadHogFunctionTemplates()
                    }
                } catch (e: any) {
                    lemonToast.error(e?.detail || e?.message || 'Failed to create template')
                    throw e
                }
            },
        },
    })),
    listeners(({ actions, props }) => ({
        showSaveAsTemplateModal: async ({ configuration }) => {
            if (props.editUserTemplateId) {
                try {
                    const template = await api.hogFunctionUserTemplates.get(props.editUserTemplateId)
                    actions.setTemplateFormValues({
                        name: configuration.name || '',
                        description: configuration.description || '',
                        tags: template.tags || [],
                        scope: template.scope || 'team',
                    })
                } catch (e: any) {
                    lemonToast.error(e?.detail || e?.message || 'Failed to load template')
                    actions.hideSaveAsTemplateModal()
                }
            } else {
                actions.setTemplateFormValues({
                    name: configuration.name || '',
                    description: configuration.description || '',
                    tags: [],
                    scope: 'team',
                })
            }
        },
    })),
])
