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
import { HOG_FUNCTION_TEMPLATES } from './templates/hog-templates'

export interface PipelineHogFunctionConfigurationLogicProps {
    templateId?: string
    id?: string
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
        resetForm: true,
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
                    const res = HOG_FUNCTION_TEMPLATES.find((template) => template.id === props.templateId)

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
            defaults: {} as HogFunctionType,
            alwaysShowErrors: true,
            errors: (data) => {
                return {
                    name: !data.name ? 'Name is required' : null,
                    ...values.inputFormErrors,
                }
            },
            submit: async (data) => {
                const sanitizedInputs = {}

                data.inputs_schema?.forEach((input) => {
                    if (input.type === 'json' && typeof data.inputs[input.key].value === 'string') {
                        try {
                            sanitizedInputs[input.key] = {
                                value: JSON.parse(data.inputs[input.key].value),
                            }
                        } catch (e) {
                            // Ignore
                        }
                    } else {
                        sanitizedInputs[input.key] = {
                            value: data.inputs[input.key].value,
                        }
                    }
                })

                const payload = {
                    ...data,
                    filters: data.filters ? sanitizeFilters(data.filters) : null,
                    inputs: sanitizedInputs,
                }

                try {
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
        loadTemplateSuccess: () => actions.resetForm(),
        loadHogFunctionSuccess: () => actions.resetForm(),
        resetForm: () => {
            const savedValue = values.hogFunction ?? values.template
            actions.resetConfiguration({
                ...savedValue,
                inputs: (savedValue as any)?.inputs ?? {},
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
