import { lemonToast } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import posthog from 'posthog-js'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { EventsNode, NodeKind, TrendsQuery } from '~/queries/schema'
import { hogql } from '~/queries/utils'
import {
    AnyPropertyFilter,
    AvailableFeature,
    BaseMathType,
    ChartDisplayType,
    FilterLogicalOperator,
    HogFunctionConfigurationType,
    HogFunctionInputType,
    HogFunctionInvocationGlobals,
    HogFunctionSubTemplateIdType,
    HogFunctionSubTemplateType,
    HogFunctionTemplateType,
    HogFunctionType,
    PipelineNodeTab,
    PipelineStage,
    PipelineTab,
    PropertyFilterType,
    PropertyGroupFilter,
} from '~/types'

import { EmailTemplate } from './email-templater/emailTemplaterLogic'
import type { hogFunctionConfigurationLogicType } from './hogFunctionConfigurationLogicType'

export interface HogFunctionConfigurationLogicProps {
    templateId?: string
    subTemplateId?: string
    id?: string
}

export const EVENT_VOLUME_DAILY_WARNING_THRESHOLD = 1000

const NEW_FUNCTION_TEMPLATE: HogFunctionTemplateType = {
    id: 'new',
    name: '',
    description: '',
    inputs_schema: [],
    hog: "print('Hello, world!');",
    status: 'stable',
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
        filters: data.filters,
        inputs: sanitizedInputs,
        masking: data.masking?.hash ? data.masking : null,
        icon_url: data.icon_url,
    }

    return payload
}

const templateToConfiguration = (
    template: HogFunctionTemplateType,
    subTemplate?: HogFunctionSubTemplateType | null
): HogFunctionConfigurationType => {
    const inputs: Record<string, HogFunctionInputType> = {}

    template.inputs_schema?.forEach((schema) => {
        if (typeof subTemplate?.inputs?.[schema.key] !== 'undefined') {
            inputs[schema.key] = { value: subTemplate.inputs[schema.key] }
        } else if (schema.default) {
            inputs[schema.key] = { value: schema.default }
        }
    })

    return {
        name: subTemplate?.name ?? template.name,
        description: subTemplate?.name ?? template.description,
        inputs_schema: template.inputs_schema,
        filters: subTemplate?.filters ?? template.filters,
        hog: template.hog,
        icon_url: template.icon_url,
        inputs,
        enabled: false,
    }
}

export const hogFunctionConfigurationLogic = kea<hogFunctionConfigurationLogicType>([
    props({} as HogFunctionConfigurationLogicProps),
    key(({ id, templateId }: HogFunctionConfigurationLogicProps) => {
        return id ?? templateId ?? 'new'
    }),
    connect({
        values: [teamLogic, ['currentTeam'], groupsModel, ['groupTypes'], userLogic, ['hasAvailableFeature']],
    }),
    path((id) => ['scenes', 'pipeline', 'hogFunctionConfigurationLogic', id]),
    actions({
        setShowSource: (showSource: boolean) => ({ showSource }),
        resetForm: true,
        upsertHogFunction: (configuration: HogFunctionConfigurationType) => ({ configuration }),
        duplicate: true,
        duplicateFromTemplate: true,
        resetToTemplate: true,
        deleteHogFunction: true,
        sparklineQueryChanged: (sparklineQuery: TrendsQuery) => ({ sparklineQuery } as { sparklineQuery: TrendsQuery }),
        setSubTemplateId: (subTemplateId: HogFunctionSubTemplateIdType | null) => ({ subTemplateId }),
    }),
    reducers({
        showSource: [
            false,
            {
                setShowSource: (_, { showSource }) => showSource,
            },
        ],

        hasHadSubmissionErrors: [
            false,
            {
                upsertHogFunctionFailure: () => true,
            },
        ],
        subTemplateId: [
            null as HogFunctionSubTemplateIdType | null,
            {
                setSubTemplateId: (_, { subTemplateId }) => subTemplateId,
            },
        ],
    }),
    loaders(({ props, values }) => ({
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

                    posthog.capture('hog function saved', {
                        id: res.id,
                        template_id: res.template?.id,
                        template_name: res.template?.name,
                    })

                    lemonToast.success('Configuration saved')

                    return res
                },
            },
        ],

        sparkline: [
            null as null | {
                data: { name: string; values: number[]; color: string }[]
                count: number
                labels: string[]
            },
            {
                sparklineQueryChanged: async ({ sparklineQuery }, breakpoint) => {
                    if (values.sparkline === null) {
                        await breakpoint(100)
                    } else {
                        await breakpoint(1000)
                    }
                    const result = await performQuery(sparklineQuery)
                    breakpoint()

                    const dataValues: number[] = result?.results?.[0]?.data ?? []
                    const [underThreshold, overThreshold] = dataValues.reduce(
                        (acc, val: number) => {
                            acc[0].push(Math.min(val, EVENT_VOLUME_DAILY_WARNING_THRESHOLD))
                            acc[1].push(Math.max(0, val - EVENT_VOLUME_DAILY_WARNING_THRESHOLD))

                            return acc
                        },
                        [[], []] as [number[], number[]]
                    )

                    const data = [
                        {
                            name: 'Low volume',
                            values: underThreshold,
                            color: 'success',
                        },
                        {
                            name: 'High volume',
                            values: overThreshold,
                            color: 'warning',
                        },
                    ]
                    const count = result?.results?.[0]?.count
                    const labels = result?.results?.[0]?.labels
                    return { data, count, labels }
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

                // Only sent on create
                ;(payload as any).template_id = props.templateId || values.hogFunction?.template?.id

                if (!values.hasAddon) {
                    // Remove the source field if the user doesn't have the addon
                    delete payload.hog
                    delete payload.inputs_schema
                }

                await asyncActions.upsertHogFunction(payload)
            },
        },
    })),
    selectors(() => ({
        logicProps: [() => [(_, props) => props], (props): HogFunctionConfigurationLogicProps => props],
        hasAddon: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => {
                return hasAvailableFeature(AvailableFeature.DATA_PIPELINES)
            },
        ],
        showPaygate: [
            (s) => [s.template, s.hasAddon],
            (template, hasAddon) => {
                return template && template.status !== 'free' && !hasAddon
            },
        ],
        defaultFormState: [
            (s) => [s.template, s.hogFunction, s.subTemplate],
            (template, hogFunction, subTemplate): HogFunctionConfigurationType | null => {
                if (template) {
                    return templateToConfiguration(template, subTemplate)
                }
                return hogFunction ?? null
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

                    const missing = value === undefined || value === null || value === ''
                    if (input.required && missing) {
                        inputErrors[key] = 'This field is required'
                    }

                    if (input.type === 'json' && typeof value === 'string') {
                        try {
                            JSON.parse(value)
                        } catch (e) {
                            inputErrors[key] = 'Invalid JSON'
                        }
                    }

                    if (input.type === 'email' && value) {
                        const emailTemplateErrors: Partial<EmailTemplate> = {
                            html: !value.html ? 'HTML is required' : undefined,
                            subject: !value.subject ? 'Subject is required' : undefined,
                            // text: !value.text ? 'Text is required' : undefined,
                            from: !value.from ? 'From is required' : undefined,
                            to: !value.to ? 'To is required' : undefined,
                        }

                        if (Object.values(emailTemplateErrors).some((v) => !!v)) {
                            inputErrors[key] = { value: emailTemplateErrors } as any
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
                const currentUrl = window.location.href.split('#')[0]
                const globals: HogFunctionInvocationGlobals = {
                    event: {
                        uuid: uuid(),
                        distinct_id: uuid(),
                        name: '$pageview',
                        timestamp: dayjs().toISOString(),
                        url: `${window.location.origin}/project/${currentTeam?.id}/events/`,
                        properties: {
                            $current_url: currentUrl,
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
                        url: currentUrl,
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
        sparklineQuery: [
            (s) => [s.configuration],
            (configuration): TrendsQuery => {
                const properties: PropertyGroupFilter = {
                    type: FilterLogicalOperator.Or,
                    values: [],
                }
                for (const event of configuration.filters?.events ?? []) {
                    const eventProperties: AnyPropertyFilter[] = [...(event.properties ?? [])]
                    if (event.id) {
                        eventProperties.push({
                            type: PropertyFilterType.HogQL,
                            key: hogql`event = ${event.id}`,
                        })
                    }
                    if (eventProperties.length === 0) {
                        eventProperties.push({
                            type: PropertyFilterType.HogQL,
                            key: 'true',
                        })
                    }
                    properties.values.push({
                        type: FilterLogicalOperator.And,
                        values: eventProperties,
                    })
                }
                for (const action of configuration.filters?.actions ?? []) {
                    const actionProperties: AnyPropertyFilter[] = [...(action.properties ?? [])]
                    if (action.id) {
                        actionProperties.push({
                            type: PropertyFilterType.HogQL,
                            key: hogql`matchesAction(${parseInt(action.id)})`,
                        })
                    }
                    properties.values.push({
                        type: FilterLogicalOperator.And,
                        values: actionProperties,
                    })
                }

                return {
                    kind: NodeKind.TrendsQuery,
                    filterTestAccounts: configuration.filters?.filter_test_accounts,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: null,
                            name: 'All Events',
                            math: BaseMathType.TotalCount,
                        } satisfies EventsNode,
                    ],
                    properties,
                    interval: 'day',
                    dateRange: {
                        date_from: '-7d',
                    },
                    trendsFilter: {
                        display: ChartDisplayType.ActionsBar,
                    },
                }
            },
            { resultEqualityCheck: equal },
        ],

        templateHasChanged: [
            (s) => [s.hogFunction, s.configuration],
            (hogFunction, configuration) => {
                return hogFunction?.template?.hog && hogFunction.template.hog !== configuration.hog
            },
        ],

        subTemplate: [
            (s) => [s.template, s.subTemplateId],
            (template, subTemplateId) => {
                if (!template || !subTemplateId) {
                    return null
                }

                const subTemplate = template.sub_templates?.find((st) => st.id === subTemplateId)
                return subTemplate
            },
        ],

        forcedSubTemplateId: [() => [router.selectors.searchParams], ({ sub_template }) => !!sub_template],
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
            const baseConfig = values.defaultFormState
            if (!baseConfig) {
                return
            }

            const config: HogFunctionConfigurationType = {
                ...baseConfig,
                ...(cache.configFromUrl ?? {}),
            }

            const paramsFromUrl = cache.paramsFromUrl ?? {}
            if (paramsFromUrl.integration_target && paramsFromUrl.integration_id) {
                config.inputs = config.inputs ?? {}
                config.inputs[paramsFromUrl.integration_target] = {
                    value: paramsFromUrl.integration_id,
                }
            }

            // TODO: Pull out sub template info

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
            const template = values.hogFunction?.template ?? values.template
            if (template) {
                const config = templateToConfiguration(template, values.subTemplate)

                const inputs = config.inputs ?? {}

                // Keep any non-default values
                Object.entries(values.configuration.inputs ?? {}).forEach(([key, value]) => {
                    inputs[key] = inputs[key] ?? value
                })

                actions.setConfigurationValues({
                    ...config,
                    filters: config.filters ?? values.configuration.filters,
                    // Keep some existing things when manually resetting the template
                    name: values.configuration.name,
                    description: values.configuration.description,
                })

                lemonToast.success('Template updates applied but not saved.')
            }
        },
        setConfigurationValue: () => {
            if (values.hasHadSubmissionErrors) {
                // Clear the manually set errors otherwise the submission won't work
                actions.setConfigurationManualErrors({})
            }
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

        setSubTemplateId: () => {
            actions.resetToTemplate()
        },
    })),
    afterMount(({ props, actions, cache }) => {
        cache.paramsFromUrl = {
            integration_id: router.values.searchParams.integration_id,
            integration_target: router.values.searchParams.integration_target,
        }

        if (props.templateId) {
            cache.configFromUrl = router.values.hashParams.configuration
            if (router.values.searchParams.sub_template) {
                actions.setSubTemplateId(router.values.searchParams.sub_template)
            }
            actions.loadTemplate() // comes with plugin info
        } else if (props.id) {
            actions.loadHogFunction()
        }

        if (router.values.searchParams.integration_target) {
            const searchParams = router.values.searchParams
            delete searchParams.integration_id
            delete searchParams.integration_target
            // Clear query params so we don't keep trying to set the integration
            router.actions.replace(router.values.location.pathname, searchParams, router.values.hashParams)
        }
    }),

    subscriptions(({ props, cache, actions }) => ({
        configuration: (configuration) => {
            if (!Object.keys(configuration).length) {
                return
            }

            if (props.templateId) {
                // Sync state to the URL bar if new
                cache.ignoreUrlChange = true
                router.actions.replace(router.values.location.pathname, router.values.searchParams, {
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

        sparklineQuery: async (sparklineQuery) => {
            actions.sparklineQueryChanged(sparklineQuery)
        },
    })),
])
