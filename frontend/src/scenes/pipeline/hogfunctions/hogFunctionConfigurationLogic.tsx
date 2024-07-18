import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import {
    FilterType,
    HogFunctionConfigurationType,
    HogFunctionInputType,
    HogFunctionInvocationGlobals,
    HogFunctionTemplateType,
    HogFunctionType,
    PipelineNodeTab,
    PipelineStage,
    PipelineTab,
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
    const sanitizedInputs: Record<string, HogFunctionInputType> = {}

    data.inputs_schema?.forEach((input) => {
        const value = data.inputs?.[input.key]?.value
        const secret = data.inputs?.[input.key]?.secret

        if (secret) {
            sanitizedInputs[input.key] = {
                value: '********', // Don't send the actual value
                secret: true,
            }
            return
        }

        if (input.type === 'json' && typeof value === 'string') {
            try {
                sanitizedInputs[input.key] = {
                    value: JSON.parse(value),
                }
            } catch (e) {
                // Ignore
            }
            return
        }
        sanitizedInputs[input.key] = {
            value: value,
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
    connect({
        values: [teamLogic, ['currentTeam'], groupsModel, ['groupTypes']],
    }),
    path((id) => ['scenes', 'pipeline', 'hogFunctionConfigurationLogic', id]),
    connect({
        values: [teamLogic, ['currentTeam'], groupsModel, ['groupTypes']],
    }),
    actions({
        setShowSource: (showSource: boolean) => ({ showSource }),
        resetForm: (configuration?: HogFunctionConfigurationType) => ({ configuration }),
        upsertHogFunction: (configuration: HogFunctionConfigurationType) => ({ configuration }),
        duplicate: true,
        duplicateFromTemplate: true,
        resetToTemplate: true,
        deleteHogFunction: true,
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
                    ...(values.inputFormErrors as any),
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
                    const inputs: Record<string, HogFunctionInputType> = {}

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
                const inputErrors: Record<string, string> = {}

                configuration.inputs_schema?.forEach((input) => {
                    const key = input.key
                    const value = inputs[key]?.value
                    if (inputs[key]?.secret) {
                        // We leave unmodified secret values alone
                        return
                    }

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
        exampleInvocationGlobals: [
            (s) => [s.configuration, s.currentTeam, s.groupTypes],
            (configuration, currentTeam, groupTypes): HogFunctionInvocationGlobals => {
                const globals: HogFunctionInvocationGlobals = {
                    event: {
                        uuid: uuid(),
                        distinct_id: uuid(),
                        name: '$pageview',
                        timestamp: dayjs().toISOString(),
                        url: `${window.location.origin}/project/${currentTeam?.id}/events/`,
                        properties: {
                            $current_url: window.location.href,
                            $browser: 'Chrome',
                        },
                    },
                    person: {
                        uuid: uuid(),
                        name: 'Example person',
                        url: `${window.location.origin}/person/${uuid()}`,
                        properties: {
                            email: 'example@posthog.com',
                        },
                    },
                    groups: {},
                    project: {
                        id: currentTeam?.id || 0,
                        name: currentTeam?.name || '',
                        url: `${window.location.origin}/project/${currentTeam?.id}`,
                    },
                    source: {
                        name: configuration?.name ?? 'Unnamed',
                        url: window.location.href,
                    },
                }

                groupTypes.forEach((groupType) => {
                    globals.groups![groupType.group_type] = {
                        id: uuid(),
                        type: groupType.group_type,
                        index: groupType.group_type_index,
                        url: `${window.location.origin}/groups/${
                            groupType.group_type_index
                        }/groups/${encodeURIComponent(groupType.group_type_index)}`,
                        properties: {},
                    }
                })

                return globals
            },
        ],
        exampleInvocationGlobalsWithInputs: [
            (s) => [s.exampleInvocationGlobals, s.configuration],
            (
                exampleInvocationGlobals,
                configuration
            ): HogFunctionInvocationGlobals & { inputs?: Record<string, any> } => {
                const inputs: Record<string, any> = {}
                for (const input of configuration?.inputs_schema || []) {
                    inputs[input.key] = input.type
                }

                return {
                    ...exampleInvocationGlobals,
                    inputs,
                }
            },
        ],
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
            const config = {
                ...values.defaultFormState,
                ...(cache.configFromUrl || {}),
            }

            const paramsFromUrl = cache.paramsFromUrl ?? {}
            if (paramsFromUrl.integration_target && paramsFromUrl.integration_id) {
                config.inputs[paramsFromUrl.integration_target] = {
                    value: paramsFromUrl.integration_id,
                }
            }

            actions.resetConfiguration(config)
        },

        duplicate: async () => {
            if (values.hogFunction) {
                const newConfig = {
                    ...values.configuration,
                    name: `${values.configuration.name} (copy)`,
                }
                const originalTemplate = values.hogFunction.template?.id ?? 'new'
                router.actions.push(
                    urls.pipelineNodeNew(PipelineStage.Destination, `hog-${originalTemplate}`),
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
                const inputs: Record<string, HogFunctionInputType> = {}

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

        deleteHogFunction: async () => {
            if (!values.hogFunction) {
                return
            }
            const { id, name } = values.hogFunction
            await deleteWithUndo({
                endpoint: `projects/${teamLogic.values.currentTeamId}/hog_functions`,
                object: {
                    id,
                    name,
                },
                callback(undo) {
                    if (undo) {
                        router.actions.replace(
                            urls.pipelineNode(PipelineStage.Destination, `hog-${id}`, PipelineNodeTab.Configuration)
                        )
                    }
                },
            })

            router.actions.replace(urls.pipeline(PipelineTab.Destinations))
        },
    })),
    afterMount(({ props, actions, cache }) => {
        cache.paramsFromUrl = {
            integration_id: router.values.searchParams.integration_id,
            integration_target: router.values.searchParams.integration_target,
        }

        if (props.templateId) {
            cache.configFromUrl = router.values.hashParams.configuration
            actions.loadTemplate() // comes with plugin info
        } else if (props.id) {
            actions.loadHogFunction()
        }

        if (router.values.searchParams.integration_target) {
            // Clear query params so we don't keep trying to set the integration
            router.actions.replace(router.values.location.pathname, undefined, router.values.hashParams)
        }
    }),

    subscriptions(({ props, cache }) => ({
        configuration: (configuration) => {
            if (!Object.keys(configuration).length) {
                return
            }

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
