import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import {
    FilterType,
    HogFunctionTemplateType,
    HogFunctionType,
    PipelineNodeTab,
    PipelineStage,
    PluginConfigFilters,
    PluginConfigTypeNew,
} from '~/types'

import type { pipelineHogFunctionConfigurationLogicType } from './pipelineHogFunctionConfigurationLogicType'

export interface PipelineHogFunctionConfigurationLogicProps {
    templateId?: string
    id?: string
}

export type HogFunctionConfigurationType = Omit<HogFunctionType, 'created_at' | 'created_by' | 'updated_at'>

const NEW_FUNCTION_TEMPLATE: HogFunctionTemplateType = {
    id: 'new',
    name: '',
    description: '',
    inputs_schema: [],
    hog: "print('Hello, world!');",
    status: 'stable',
}

function sanitizeFilters(filters?: FilterType): PluginConfigTypeNew['filters'] {
    if (!filters) {
        return null
    }
    const sanitized: PluginConfigFilters = {}

    if (filters.events) {
        sanitized.events = filters.events.map((f) => ({
            id: f.id,
            type: 'events',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    if (filters.actions) {
        sanitized.actions = filters.actions.map((f) => ({
            id: f.id,
            type: 'actions',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    if (filters.filter_test_accounts) {
        sanitized.filter_test_accounts = filters.filter_test_accounts
    }

    return Object.keys(sanitized).length > 0 ? sanitized : undefined
}

// Should likely be somewhat similar to pipelineBatchExportConfigurationLogic
export const pipelineHogFunctionConfigurationLogic = kea<pipelineHogFunctionConfigurationLogicType>([
    props({} as PipelineHogFunctionConfigurationLogicProps),
    key(({ id, templateId }: PipelineHogFunctionConfigurationLogicProps) => {
        return id ?? templateId ?? 'new'
    }),
    path((id) => ['scenes', 'pipeline', 'pipelineHogFunctionConfigurationLogic', id]),
    actions({
        setShowSource: (showSource: boolean) => ({ showSource }),
        resetForm: (configuration?: HogFunctionConfigurationType) => ({ configuration }),
        duplicate: true,
        duplicateFromTemplate: true,
        resetToTemplate: true,
    }),
    reducers({
        showSource: [
            false,
            {
                setShowSource: (_, { showSource }) => showSource,
            },
        ],
    }),
    loaders(({ props }) => ({
        template: [
            null as HogFunctionTemplateType | null,
            {
                loadTemplate: async () => {
                    if (!props.templateId) {
                        return null
                    }

                    if (props.templateId === 'new') {
                        return {
                            ...NEW_FUNCTION_TEMPLATE,
                        }
                    }

                    const res = await api.hogFunctions.getTemplate(props.templateId)

                    if (!res) {
                        throw new Error('Template not found')
                    }
                    return res
                },
            },
        ],

        hogFunction: [
            null as HogFunctionType | null,
            {
                loadHogFunction: async () => {
                    if (!props.id) {
                        return null
                    }

                    return await api.hogFunctions.get(props.id)
                },
            },
        ],
    })),
    forms(({ values, props, actions }) => ({
        configuration: {
            defaults: {} as HogFunctionConfigurationType,
            alwaysShowErrors: true,
            errors: (data) => {
                return {
                    name: !data.name ? 'Name is required' : undefined,
                    ...values.inputFormErrors,
                }
            },
            submit: async (data) => {
                try {
                    const sanitizedInputs = {}

                    data.inputs_schema?.forEach((input) => {
                        const value = data.inputs?.[input.key]?.value

                        if (input.type === 'json' && typeof value === 'string') {
                            try {
                                sanitizedInputs[input.key] = {
                                    value: JSON.parse(value),
                                }
                            } catch (e) {
                                // Ignore
                            }
                        } else {
                            sanitizedInputs[input.key] = {
                                value: value,
                            }
                        }
                    })

                    const payload: HogFunctionConfigurationType = {
                        ...data,
                        filters: data.filters ? sanitizeFilters(data.filters) : null,
                        inputs: sanitizedInputs,
                        icon_url: data.icon_url?.replace('&temp=true', ''), // Remove temp=true so it doesn't try and suggest new options next time
                    }

                    if (props.templateId) {
                        // Only sent on create
                        ;(payload as any).template_id = props.templateId
                    }

                    if (!props.id) {
                        return await api.hogFunctions.create(payload)
                    }
                    return await api.hogFunctions.update(props.id, payload)
                } catch (e) {
                    const maybeValidationError = (e as any).data
                    if (maybeValidationError?.type === 'validation_error') {
                        if (maybeValidationError.attr.includes('inputs__')) {
                            actions.setConfigurationManualErrors({
                                inputs: {
                                    [maybeValidationError.attr.split('__')[1]]: maybeValidationError.detail,
                                },
                            })
                        } else {
                            actions.setConfigurationManualErrors({
                                [maybeValidationError.attr]: maybeValidationError.detail,
                            })
                        }
                    } else {
                        console.error(e)
                        lemonToast.error('Error submitting configuration')
                    }

                    throw e
                }
            },
        },
    })),
    selectors(() => ({
        loading: [
            (s) => [s.hogFunctionLoading, s.templateLoading],
            (hogFunctionLoading, templateLoading) => hogFunctionLoading || templateLoading,
        ],
        loaded: [(s) => [s.hogFunction, s.template], (hogFunction, template) => !!hogFunction || !!template],

        inputFormErrors: [
            (s) => [s.configuration],
            (configuration) => {
                const inputs = configuration.inputs ?? {}
                const inputErrors = {}

                configuration.inputs_schema?.forEach((input) => {
                    if (input.required && !inputs[input.key]) {
                        inputErrors[input.key] = 'This field is required'
                    }

                    if (input.type === 'json' && typeof inputs[input.key] === 'string') {
                        try {
                            JSON.parse(inputs[input.key].value)
                        } catch (e) {
                            inputErrors[input.key] = 'Invalid JSON'
                        }
                    }
                })

                return Object.keys(inputErrors).length > 0
                    ? {
                          inputs: inputErrors,
                      }
                    : null
            },
        ],
    })),

    listeners(({ actions, values, cache, props }) => ({
        loadTemplateSuccess: ({ template }) => {
            // Fill defaults from template
            const inputs = {}

            template!.inputs_schema?.forEach((schema) => {
                if (schema.default) {
                    inputs[schema.key] = { value: schema.default }
                }
            })

            actions.resetForm({
                ...template!,
                inputs,
                enabled: false,
            })
        },
        loadHogFunctionSuccess: ({ hogFunction }) => actions.resetForm(hogFunction),

        resetForm: ({ configuration }) => {
            const savedValue = configuration
            actions.resetConfiguration({
                ...savedValue,
                inputs: savedValue?.inputs ?? {},
                ...(cache.configFromUrl || {}),
            })
        },

        submitConfigurationSuccess: ({ configuration }) => {
            if (!props.id) {
                router.actions.replace(
                    urls.pipelineNode(
                        PipelineStage.Destination,
                        `hog-${configuration.id}`,
                        PipelineNodeTab.Configuration
                    )
                )
            }
        },

        duplicate: async () => {
            if (values.hogFunction) {
                const newConfig = {
                    ...values.configuration,
                    name: `${values.configuration.name} (copy)`,
                }
                router.actions.push(
                    urls.pipelineNodeNew(PipelineStage.Destination, `hog-template-helloworld`),
                    undefined,
                    {
                        configuration: newConfig,
                    }
                )
            }
        },
        duplicateFromTemplate: async () => {
            if (values.hogFunction?.template) {
                const newConfig = {
                    ...values.hogFunction.template,
                }
                router.actions.push(
                    urls.pipelineNodeNew(PipelineStage.Destination, `hog-${values.hogFunction.template.id}`),
                    undefined,
                    {
                        configuration: newConfig,
                    }
                )
            }
        },
        resetToTemplate: async () => {
            if (values.hogFunction?.template) {
                actions.resetForm({
                    ...values.hogFunction.template,
                    enabled: false,
                })
            }
        },
    })),
    afterMount(({ props, actions, cache }) => {
        if (props.templateId) {
            cache.configFromUrl = router.values.hashParams.configuration
            actions.loadTemplate() // comes with plugin info
        } else if (props.id) {
            actions.loadHogFunction()
        }
    }),

    subscriptions(({ props, cache }) => ({
        configuration: (configuration) => {
            if (props.templateId) {
                // Sync state to the URL bar if new
                cache.ignoreUrlChange = true
                router.actions.replace(router.values.location.pathname, undefined, {
                    configuration,
                })
            }
        },
    })),
])
