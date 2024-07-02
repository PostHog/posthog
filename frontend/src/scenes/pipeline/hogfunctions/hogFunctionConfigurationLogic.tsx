import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { createExampleEvent } from 'scenes/pipeline/hogfunctions/utils/event-conversion'
import { urls } from 'scenes/urls'

import {
    FilterType,
    HogFunctionConfigurationType,
    HogFunctionTemplateType,
    HogFunctionType,
    PipelineNodeTab,
    PipelineStage,
    PluginConfigFilters,
    PluginConfigTypeNew,
} from '~/types'

import type { hogFunctionConfigurationLogicType } from './hogFunctionConfigurationLogicType'

export interface HogFunctionConfigurationLogicProps {
    templateId?: string
    id?: string
}

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

export function sanitizeConfiguration(data: HogFunctionConfigurationType): HogFunctionConfigurationType {
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

    return payload
}

export const hogFunctionConfigurationLogic = kea<hogFunctionConfigurationLogicType>([
    props({} as HogFunctionConfigurationLogicProps),
    key(({ id, templateId }: HogFunctionConfigurationLogicProps) => {
        return id ?? templateId ?? 'new'
    }),
    path((id) => ['scenes', 'pipeline', 'hogFunctionConfigurationLogic', id]),
    actions({
        setShowSource: (showSource: boolean) => ({ showSource }),
        resetForm: (configuration?: HogFunctionConfigurationType) => ({ configuration }),
        upsertHogFunction: (configuration: HogFunctionConfigurationType) => ({ configuration }),
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

                upsertHogFunction: async ({ configuration }) => {
                    const res = props.id
                        ? await api.hogFunctions.update(props.id, configuration)
                        : await api.hogFunctions.create(configuration)

                    lemonToast.success('Configuration saved')

                    return res
                },
            },
        ],
    })),
    forms(({ values, props, asyncActions }) => ({
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
                const payload = sanitizeConfiguration(data)

                if (props.templateId) {
                    // Only sent on create
                    ;(payload as any).template_id = props.templateId
                }

                await asyncActions.upsertHogFunction(payload)
            },
        },
    })),
    selectors(() => ({
        defaultFormState: [
            (s) => [s.template, s.hogFunction],
            (template, hogFunction): HogFunctionConfigurationType => {
                if (template) {
                    // Fill defaults from template
                    const inputs = {}

                    template.inputs_schema?.forEach((schema) => {
                        if (schema.default) {
                            inputs[schema.key] = { value: schema.default }
                        }
                    })

                    return {
                        ...template,
                        inputs,
                        enabled: false,
                    }
                } else if (hogFunction) {
                    return hogFunction
                }
                return {} as HogFunctionConfigurationType
            },
        ],

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
                    const key = input.key
                    const value = inputs[key]?.value
                    if (input.required && !value) {
                        inputErrors[key] = 'This field is required'
                    }

                    if (input.type === 'json' && typeof value === 'string') {
                        try {
                            JSON.parse(value)
                        } catch (e) {
                            inputErrors[key] = 'Invalid JSON'
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

        willReEnableOnSave: [
            (s) => [s.configuration, s.hogFunction],
            (configuration, hogFunction) => {
                return configuration?.enabled && (hogFunction?.status?.state ?? 0) >= 3
            },
        ],
        // TODO: connect to the actual globals
        globalVars: [(s) => [s.hogFunction], (): Record<string, any> => createExampleEvent()],
    })),

    listeners(({ actions, values, cache }) => ({
        loadTemplateSuccess: () => actions.resetForm(),
        loadHogFunctionSuccess: () => actions.resetForm(),
        upsertHogFunctionSuccess: () => actions.resetForm(),

        upsertHogFunctionFailure: ({ errorObject }) => {
            const maybeValidationError = errorObject.data

            if (maybeValidationError?.type === 'validation_error') {
                setTimeout(() => {
                    // TRICKY: We want to run on the next tick otherwise the errors don't show (possibly because of the async wait in the submit)
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
                }, 1)
            } else {
                console.error(errorObject)
                lemonToast.error('Error submitting configuration')
            }
        },

        resetForm: () => {
            actions.resetConfiguration({
                ...values.defaultFormState,
                ...(cache.configFromUrl || {}),
            })
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
                const template = values.hogFunction.template
                // Fill defaults from template
                const inputs = {}

                template.inputs_schema?.forEach((schema) => {
                    if (schema.default) {
                        inputs[schema.key] = { value: schema.default }
                    }
                })

                actions.setConfigurationValues({
                    ...values.hogFunction.template,
                    filters: values.configuration.filters ?? template.filters,
                    // Keep some existing things
                    name: values.configuration.name,
                    description: values.configuration.description,
                    inputs,
                    enabled: false,
                })
            }
        },
        setConfigurationValue: () => {
            // Clear the manually set errors otherwise the submission won't work
            actions.setConfigurationManualErrors({})
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

        hogFunction: (hogFunction) => {
            if (hogFunction && props.templateId) {
                // Catch all for any scenario where we need to redirect away from the template to the actual hog function
                router.actions.replace(
                    urls.pipelineNode(PipelineStage.Destination, `hog-${hogFunction.id}`, PipelineNodeTab.Configuration)
                )
            }
        },
    })),
])
