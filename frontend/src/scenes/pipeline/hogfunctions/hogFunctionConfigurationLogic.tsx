import { lemonToast } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { actions, afterMount, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import posthog from 'posthog-js'
import { asDisplay } from 'scenes/persons/person-utils'
import { hogFunctionNewUrl, hogFunctionUrl } from 'scenes/pipeline/hogfunctions/urls'
import { pipelineNodeLogic } from 'scenes/pipeline/pipelineNodeLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { performQuery } from '~/queries/query'
import {
    ActorsQuery,
    DataTableNode,
    EventsNode,
    EventsQuery,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { escapePropertyAsHogQlIdentifier, hogql } from '~/queries/utils'
import {
    AnyPersonScopeFilter,
    AnyPropertyFilter,
    AvailableFeature,
    BaseMathType,
    ChartDisplayType,
    EventType,
    FilterLogicalOperator,
    HogFunctionConfigurationType,
    HogFunctionInputSchemaType,
    HogFunctionInputType,
    HogFunctionInvocationGlobals,
    HogFunctionMappingType,
    HogFunctionTemplateType,
    HogFunctionType,
    HogFunctionTypeType,
    PersonType,
    PipelineNodeTab,
    PipelineStage,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
} from '~/types'

import { EmailTemplate } from './email-templater/emailTemplaterLogic'
import type { hogFunctionConfigurationLogicType } from './hogFunctionConfigurationLogicType'

export interface HogFunctionConfigurationLogicProps {
    logicKey?: string
    templateId?: string | null
    id?: string | null
}

export const EVENT_VOLUME_DAILY_WARNING_THRESHOLD = 1000
const UNSAVED_CONFIGURATION_TTL = 1000 * 60 * 5

const NEW_FUNCTION_TEMPLATE: HogFunctionTemplateType = {
    id: 'new',
    free: false,
    type: 'destination',
    name: '',
    description: '',
    inputs_schema: [],
    hog: "print('Hello, world!');",
    status: 'stable',
}

export const TYPES_WITH_GLOBALS: HogFunctionTypeType[] = ['transformation', 'destination']

export function sanitizeConfiguration(data: HogFunctionConfigurationType): HogFunctionConfigurationType {
    function sanitizeInputs(
        data: HogFunctionConfigurationType | HogFunctionMappingType
    ): Record<string, HogFunctionInputType> {
        const sanitizedInputs: Record<string, HogFunctionInputType> = {}
        data.inputs_schema?.forEach((input) => {
            const secret = data.inputs?.[input.key]?.secret
            let value = data.inputs?.[input.key]?.value

            if (secret) {
                // If set this means we haven't changed the value
                sanitizedInputs[input.key] = {
                    value: '********', // Don't send the actual value
                    secret: true,
                }
                return
            }

            if (input.type === 'json' && typeof value === 'string') {
                try {
                    value = JSON.parse(value)
                } catch (e) {
                    // Ignore
                }
            }

            sanitizedInputs[input.key] = {
                value: value,
            }
        })
        return sanitizedInputs
    }

    const payload: HogFunctionConfigurationType = {
        ...data,
        filters: data.filters,
        mappings: data.mappings?.map((mapping) => ({
            ...mapping,
            inputs: sanitizeInputs(mapping),
        })),
        inputs: sanitizeInputs(data),
        masking: data.masking?.hash ? data.masking : null,
        icon_url: data.icon_url,
    }

    return payload
}

const templateToConfiguration = (template: HogFunctionTemplateType): HogFunctionConfigurationType => {
    function getInputs(inputs_schema?: HogFunctionInputSchemaType[] | null): Record<string, HogFunctionInputType> {
        const inputs: Record<string, HogFunctionInputType> = {}
        inputs_schema?.forEach((schema) => {
            if (schema.default !== undefined) {
                inputs[schema.key] = { value: schema.default }
            }
        })
        return inputs
    }

    function getMappingInputs(
        inputs_schema?: HogFunctionInputSchemaType[] | null
    ): Record<string, HogFunctionInputType> {
        const inputs: Record<string, HogFunctionInputType> = {}
        inputs_schema?.forEach((schema) => {
            if (schema.default !== undefined) {
                inputs[schema.key] = { value: schema.default }
            }
        })
        return inputs
    }

    return {
        type: template.type ?? 'destination',
        name: template.name,
        description: template.description,
        inputs_schema: template.inputs_schema,
        filters: template.filters,
        mappings: template.mappings?.map(
            (mapping): HogFunctionMappingType => ({
                ...mapping,
                inputs: getMappingInputs(mapping.inputs_schema),
            })
        ),
        hog: template.hog,
        icon_url: template.icon_url,
        inputs: getInputs(template.inputs_schema),
        enabled: template.type !== 'broadcast',
    }
}

export function convertToHogFunctionInvocationGlobals(
    event: EventType,
    person: PersonType
): HogFunctionInvocationGlobals {
    const team = teamLogic.findMounted()?.values?.currentTeam
    const projectUrl = `${window.location.origin}/project/${team?.id}`
    return {
        project: {
            id: team?.id ?? 0,
            name: team?.name ?? 'Default project',
            url: projectUrl,
        },
        event: {
            uuid: event.uuid ?? '',
            event: event.event,
            distinct_id: event.distinct_id,
            elements_chain: event.elements_chain ?? '',
            properties: event.properties,
            timestamp: event.timestamp,

            url: `${projectUrl}/events/${encodeURIComponent(event.uuid ?? '')}/${encodeURIComponent(event.timestamp)}`,
        },
        person: {
            id: person.uuid ?? '',
            properties: person.properties,

            name: asDisplay(person),
            url: `${projectUrl}/person/${encodeURIComponent(event.distinct_id)}`,
        },
        groups: {},
    }
}

export const hogFunctionConfigurationLogic = kea<hogFunctionConfigurationLogicType>([
    path((id) => ['scenes', 'pipeline', 'hogFunctionConfigurationLogic', id]),
    props({} as HogFunctionConfigurationLogicProps),
    key(({ id, templateId, logicKey }: HogFunctionConfigurationLogicProps) => {
        const baseKey = id ?? templateId ?? 'new'
        return logicKey ? `${logicKey}_${baseKey}` : baseKey
    }),
    connect(({ id }: HogFunctionConfigurationLogicProps) => ({
        values: [
            projectLogic,
            ['currentProjectId', 'currentProject'],
            groupsModel,
            ['groupTypes'],
            userLogic,
            ['hasAvailableFeature'],
        ],
        actions: [pipelineNodeLogic({ id: `hog-${id}`, stage: PipelineStage.Destination }), ['setBreadcrumbTitle']],
    })),
    actions({
        setShowSource: (showSource: boolean) => ({ showSource }),
        resetForm: true,
        upsertHogFunction: (configuration: HogFunctionConfigurationType) => ({ configuration }),
        duplicate: true,
        duplicateFromTemplate: true,
        resetToTemplate: true,
        deleteHogFunction: true,
        sparklineQueryChanged: (sparklineQuery: TrendsQuery) => ({ sparklineQuery } as { sparklineQuery: TrendsQuery }),
        personsCountQueryChanged: (personsCountQuery: ActorsQuery) =>
            ({ personsCountQuery } as { personsCountQuery: ActorsQuery }),
        loadSampleGlobals: true,
        setUnsavedConfiguration: (configuration: HogFunctionConfigurationType | null) => ({ configuration }),
        persistForUnload: true,
        setSampleGlobalsError: (error) => ({ error }),
        setSampleGlobals: (sampleGlobals: HogFunctionInvocationGlobals | null) => ({ sampleGlobals }),
        setShowEventsList: (showEventsList: boolean) => ({ showEventsList }),
    }),
    reducers(({ props }) => ({
        sampleGlobals: [
            null as HogFunctionInvocationGlobals | null,
            {
                setSampleGlobals: (_, { sampleGlobals }) => sampleGlobals,
            },
        ],
        showSource: [
            // Show source by default for blank templates when creating a new function
            !!(!props.id && props.templateId?.startsWith('template-blank-')),
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

        unsavedConfiguration: [
            null as { timestamp: number; configuration: HogFunctionConfigurationType } | null,
            { persist: true },
            {
                setUnsavedConfiguration: (_, { configuration }) =>
                    configuration ? { timestamp: Date.now(), configuration } : null,
            },
        ],

        sampleGlobalsError: [
            null as null | string,
            {
                loadSampleGlobals: () => null,
                setSampleGlobalsError: (_, { error }) => error,
            },
        ],
        showEventsList: [
            false,
            {
                setShowEventsList: (_, { showEventsList }) => showEventsList,
            },
        ],
    })),
    loaders(({ actions, props, values }) => ({
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
                    if (!props.id || props.id === 'new') {
                        return null
                    }

                    return await api.hogFunctions.get(props.id)
                },

                upsertHogFunction: async ({ configuration }) => {
                    const res =
                        props.id && props.id !== 'new'
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
                    if (!['destination', 'site_destination', 'transformation'].includes(values.type)) {
                        return null
                    }
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

        personsCount: [
            null as number | null,
            {
                personsCountQueryChanged: async ({ personsCountQuery }, breakpoint) => {
                    if (values.type !== 'broadcast') {
                        return null
                    }
                    if (values.personsCount === null) {
                        await breakpoint(100)
                    } else {
                        await breakpoint(1000)
                    }
                    const result = await performQuery(personsCountQuery)
                    breakpoint()
                    return result?.results?.[0]?.[0] ?? null
                },
            },
        ],

        sampleGlobals: [
            null as HogFunctionInvocationGlobals | null,
            {
                loadSampleGlobals: async (_, breakpoint) => {
                    if (!values.lastEventQuery) {
                        return values.sampleGlobals
                    }
                    const errorMessage =
                        'No events match these filters in the last 30 days. Showing an example $pageview event instead.'
                    try {
                        await breakpoint(values.sampleGlobals === null ? 10 : 1000)
                        let response = await performQuery(values.lastEventQuery)
                        if (!response?.results?.[0] && values.lastEventSecondQuery) {
                            response = await performQuery(values.lastEventSecondQuery)
                        }
                        if (!response?.results?.[0]) {
                            throw new Error(errorMessage)
                        }
                        const event: EventType = response?.results?.[0]?.[0]
                        const person: PersonType = response?.results?.[0]?.[1]
                        const globals = convertToHogFunctionInvocationGlobals(event, person)
                        globals.groups = {}
                        values.groupTypes.forEach((groupType, index) => {
                            const tuple = response?.results?.[0]?.[2 + index]
                            if (tuple && Array.isArray(tuple) && tuple[2]) {
                                let properties = {}
                                try {
                                    properties = JSON.parse(tuple[3])
                                } catch (e) {
                                    // Ignore
                                }
                                globals.groups![groupType.group_type] = {
                                    type: groupType.group_type,
                                    index: tuple[1],
                                    id: tuple[2], // TODO: rename to "key"?
                                    url: `${window.location.origin}/groups/${tuple[1]}/${encodeURIComponent(tuple[2])}`,
                                    properties,
                                }
                            }
                        })
                        globals.source = {
                            name: values.configuration?.name ?? 'Unnamed',
                            url: window.location.href.split('#')[0],
                        }
                        return globals
                    } catch (e: any) {
                        if (!isBreakpoint(e)) {
                            actions.setSampleGlobalsError(e.message ?? errorMessage)
                        }
                        return values.exampleInvocationGlobals
                    }
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
                    mappings:
                        data.type === 'site_destination' && (!data.mappings || data.mappings.length === 0)
                            ? 'You must add at least one mapping'
                            : undefined,
                    filters:
                        data.type === 'internal_destination' && data.filters?.events?.length === 0
                            ? 'You must choose a filter'
                            : undefined,
                    ...(values.inputFormErrors as any),
                }
            },
            submit: async (data) => {
                const payload: Record<string, any> = sanitizeConfiguration(data)
                // Only sent on create
                payload.template_id = props.templateId || values.hogFunction?.template?.id

                if (!values.hasAddon) {
                    // Remove the source field if the user doesn't have the addon
                    delete payload.hog
                    delete payload.inputs_schema
                }

                await asyncActions.upsertHogFunction(payload as HogFunctionConfigurationType)
            },
        },
    })),
    selectors(() => ({
        logicProps: [() => [(_, props) => props], (props): HogFunctionConfigurationLogicProps => props],
        type: [
            (s) => [s.configuration, s.hogFunction],
            (configuration, hogFunction) => configuration?.type ?? hogFunction?.type ?? 'loading',
        ],
        hasAddon: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => {
                return hasAvailableFeature(AvailableFeature.DATA_PIPELINES)
            },
        ],
        hasGroupsAddon: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => {
                return hasAvailableFeature(AvailableFeature.GROUP_ANALYTICS)
            },
        ],
        showPaygate: [
            (s) => [s.template, s.hasAddon],
            (template, hasAddon) => {
                return template && !template.free && !hasAddon
            },
        ],
        useMapping: [
            (s) => [s.hogFunction, s.template],
            // If the function has mappings, or the template has mapping templates, we use mappings
            (hogFunction, template) => Array.isArray(hogFunction?.mappings) || template?.mapping_templates?.length,
        ],
        defaultFormState: [
            (s) => [s.template, s.hogFunction],
            (template, hogFunction): HogFunctionConfigurationType | null => {
                if (template) {
                    return templateToConfiguration(template)
                }
                return hogFunction ?? null
            },
        ],

        templateId: [
            (s) => [s.template, s.hogFunction],
            (template, hogFunction) => template?.id || hogFunction?.template?.id,
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

        willChangeEnabledOnSave: [
            (s) => [s.configuration, s.hogFunction],
            (configuration, hogFunction) => {
                return configuration?.enabled !== (hogFunction?.enabled ?? false)
            },
        ],
        exampleInvocationGlobals: [
            (s) => [s.configuration, s.currentProject, s.groupTypes],
            (configuration, currentProject, groupTypes): HogFunctionInvocationGlobals => {
                const currentUrl = window.location.href.split('#')[0]
                const eventId = uuid()
                const personId = uuid()
                const globals: HogFunctionInvocationGlobals = {
                    event: {
                        uuid: eventId,
                        distinct_id: uuid(),
                        event: '$pageview',
                        timestamp: dayjs().toISOString(),
                        elements_chain: '',
                        properties: {
                            $current_url: currentUrl,
                            $browser: 'Chrome',
                        },
                        url: `${window.location.origin}/project/${currentProject?.id}/events/`,
                    },
                    person: {
                        id: personId,
                        properties: {
                            email: 'example@posthog.com',
                        },
                        name: 'Example person',
                        url: `${window.location.origin}/person/${personId}`,
                    },
                    groups: {},
                    project: {
                        id: currentProject?.id || 0,
                        name: currentProject?.name || '',
                        url: `${window.location.origin}/project/${currentProject?.id}`,
                    },
                    source: {
                        name: configuration?.name ?? 'Unnamed',
                        url: currentUrl,
                    },
                }
                groupTypes.forEach((groupType) => {
                    const id = uuid()
                    globals.groups![groupType.group_type] = {
                        id: id,
                        type: groupType.group_type,
                        index: groupType.group_type_index,
                        url: `${window.location.origin}/groups/${groupType.group_type_index}/${encodeURIComponent(id)}`,
                        properties: {},
                    }
                })

                return globals
            },
        ],
        globalsWithInputs: [
            (s) => [s.sampleGlobals, s.exampleInvocationGlobals, s.configuration],
            (
                sampleGlobals,
                exampleInvocationGlobals,
                configuration
            ): HogFunctionInvocationGlobals & { inputs?: Record<string, any> } => {
                const inputs: Record<string, any> = {}
                for (const input of configuration?.inputs_schema || []) {
                    inputs[input.key] = input.type
                }

                return {
                    ...(sampleGlobals ?? exampleInvocationGlobals),
                    inputs,
                }
            },
        ],
        matchingFilters: [
            (s) => [s.configuration, s.useMapping],
            (configuration, useMapping): PropertyGroupFilter => {
                // We're using mappings, but none are provided, so match zero events.
                if (useMapping && !configuration.mappings?.length) {
                    return {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.HogQL,
                                        key: 'false',
                                    },
                                ],
                            },
                        ],
                    }
                }

                const seriesProperties: PropertyGroupFilterValue = {
                    type: FilterLogicalOperator.Or,
                    values: [],
                }
                const properties: PropertyGroupFilter = {
                    type: FilterLogicalOperator.And,
                    values: [seriesProperties],
                }
                const allPossibleEventFilters = configuration.filters?.events ?? []
                const allPossibleActionFilters = configuration.filters?.actions ?? []

                if (Array.isArray(configuration.mappings)) {
                    for (const mapping of configuration.mappings) {
                        if (mapping.filters?.events) {
                            allPossibleEventFilters.push(...mapping.filters.events)
                        }
                        if (mapping.filters?.actions) {
                            allPossibleActionFilters.push(...mapping.filters.actions)
                        }
                    }
                }

                for (const event of allPossibleEventFilters) {
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
                    seriesProperties.values.push({
                        type: FilterLogicalOperator.And,
                        values: eventProperties,
                    })
                }
                for (const action of allPossibleActionFilters) {
                    const actionProperties: AnyPropertyFilter[] = [...(action.properties ?? [])]
                    if (action.id) {
                        actionProperties.push({
                            type: PropertyFilterType.HogQL,
                            key: hogql`matchesAction(${parseInt(action.id)})`,
                        })
                    }
                    seriesProperties.values.push({
                        type: FilterLogicalOperator.And,
                        values: actionProperties,
                    })
                }
                if ((configuration.filters?.properties?.length ?? 0) > 0) {
                    const globalProperties: PropertyGroupFilterValue = {
                        type: FilterLogicalOperator.And,
                        values: [],
                    }
                    for (const property of configuration.filters?.properties ?? []) {
                        globalProperties.values.push(property as AnyPropertyFilter)
                    }
                    properties.values.push(globalProperties)
                }
                return properties
            },
            { resultEqualityCheck: equal },
        ],

        filtersContainPersonProperties: [
            (s) => [s.configuration],
            (configuration) => {
                const filters = configuration.filters
                let containsPersonProperties = false
                if (filters?.properties && !containsPersonProperties) {
                    containsPersonProperties = filters.properties.some((p) => p.type === 'person')
                }
                if (filters?.actions && !containsPersonProperties) {
                    containsPersonProperties = filters.actions.some((a) =>
                        a.properties?.some((p) => p.type === 'person')
                    )
                }
                if (filters?.events && !containsPersonProperties) {
                    containsPersonProperties = filters.events.some((e) =>
                        e.properties?.some((p) => p.type === 'person')
                    )
                }
                return containsPersonProperties
            },
        ],

        sparklineQuery: [
            (s) => [s.configuration, s.matchingFilters, s.type],
            (configuration, matchingFilters, type): TrendsQuery | null => {
                if (!['destination', 'site_destination', 'transformation'].includes(type)) {
                    return null
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
                    properties: matchingFilters,
                    interval: 'day',
                    dateRange: {
                        date_from: '-7d',
                    },
                    trendsFilter: {
                        display: ChartDisplayType.ActionsBar,
                    },
                    modifiers: {
                        personsOnEventsMode: 'person_id_no_override_properties_on_events',
                    },
                }
            },
            { resultEqualityCheck: equal },
        ],

        personsCountQuery: [
            (s) => [s.configuration, s.type],
            (configuration, type): ActorsQuery | null => {
                if (type !== 'broadcast') {
                    return null
                }
                return {
                    kind: NodeKind.ActorsQuery,
                    properties: configuration.filters?.properties as AnyPersonScopeFilter[] | undefined,
                    select: ['count()'],
                }
            },
            { resultEqualityCheck: equal },
        ],

        personsListQuery: [
            (s) => [s.configuration, s.type],
            (configuration, type): DataTableNode | null => {
                if (type !== 'broadcast') {
                    return null
                }
                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.ActorsQuery,
                        properties: configuration.filters?.properties as AnyPersonScopeFilter[] | undefined,
                        select: ['person', 'properties.email', 'created_at'],
                    },
                    full: true,
                }
            },
            { resultEqualityCheck: equal },
        ],

        baseEventsQuery: [
            (s) => [s.configuration, s.matchingFilters, s.groupTypes, s.type],
            (configuration, matchingFilters, groupTypes, type): EventsQuery | null => {
                if (!TYPES_WITH_GLOBALS.includes(type)) {
                    return null
                }
                const query: EventsQuery = {
                    kind: NodeKind.EventsQuery,
                    filterTestAccounts: configuration.filters?.filter_test_accounts,
                    fixedProperties: [matchingFilters],
                    select: ['*', 'person'],
                    after: '-7d',
                    orderBy: ['timestamp DESC'],
                    modifiers: {
                        // NOTE: We always want to show events with the person properties at the time the event was created as that is what the function will see
                        personsOnEventsMode: 'person_id_no_override_properties_on_events',
                    },
                }
                groupTypes.forEach((groupType) => {
                    const name = escapePropertyAsHogQlIdentifier(groupType.group_type)
                    query.select.push(
                        `tuple(${name}.created_at, ${name}.index, ${name}.key, ${name}.properties, ${name}.updated_at)`
                    )
                })
                return query
            },
            { resultEqualityCheck: equal },
        ],

        eventsDataTableNode: [
            (s) => [s.baseEventsQuery],
            (baseEventsQuery): DataTableNode | null => {
                return baseEventsQuery
                    ? {
                          kind: NodeKind.DataTableNode,
                          source: {
                              ...baseEventsQuery,
                              select: defaultDataTableColumns(NodeKind.EventsQuery),
                          },
                      }
                    : null
            },
        ],

        lastEventQuery: [
            (s) => [s.baseEventsQuery],
            (baseEventsQuery): EventsQuery | null => {
                return baseEventsQuery ? { ...baseEventsQuery, limit: 1 } : null
            },
            { resultEqualityCheck: equal },
        ],
        lastEventSecondQuery: [
            (s) => [s.lastEventQuery],
            (lastEventQuery): EventsQuery | null => (lastEventQuery ? { ...lastEventQuery, after: '-30d' } : null),
        ],
        templateHasChanged: [
            (s) => [s.hogFunction, s.configuration],
            (hogFunction, configuration) => {
                return hogFunction?.template?.hog && hogFunction.template.hog !== configuration.hog
            },
        ],
        mappingTemplates: [
            (s) => [s.hogFunction, s.template],
            (hogFunction, template) => template?.mapping_templates ?? hogFunction?.template?.mapping_templates ?? [],
        ],

        usesGroups: [
            (s) => [s.configuration],
            (configuration) => {
                // NOTE: Bit hacky but works good enough...
                const configStr = JSON.stringify(configuration)
                return configStr.includes('groups.') || configStr.includes('{groups}')
            },
        ],
    })),

    listeners(({ actions, values, cache }) => ({
        loadTemplateSuccess: () => actions.resetForm(),
        loadHogFunctionSuccess: () => {
            actions.resetForm()
            actions.setBreadcrumbTitle(values.hogFunction?.name ?? 'Unnamed')
        },
        upsertHogFunctionSuccess: () => {
            actions.resetForm()
            actions.setBreadcrumbTitle(values.hogFunction?.name ?? 'Unnamed')
        },

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

            if (values.template?.mapping_templates) {
                config.mappings = [
                    ...(config.mappings ?? []),
                    ...values.template.mapping_templates
                        .filter((t) => t.include_by_default)
                        .map((template) => ({
                            ...template,
                            inputs: template.inputs_schema?.reduce((acc, input) => {
                                acc[input.key] = { value: input.default }
                                return acc
                            }, {} as Record<string, HogFunctionInputType>),
                        })),
                ]
            }
            const paramsFromUrl = cache.paramsFromUrl ?? {}
            const unsavedConfigurationToApply =
                (values.unsavedConfiguration?.timestamp ?? 0) > Date.now() - UNSAVED_CONFIGURATION_TTL
                    ? values.unsavedConfiguration?.configuration
                    : null

            actions.resetConfiguration(config)

            if (unsavedConfigurationToApply) {
                actions.setConfigurationValues(unsavedConfigurationToApply)
            }

            actions.setUnsavedConfiguration(null)

            if (paramsFromUrl.integration_target && paramsFromUrl.integration_id) {
                const inputs = values.configuration?.inputs ?? {}
                inputs[paramsFromUrl.integration_target] = {
                    value: paramsFromUrl.integration_id,
                }

                actions.setConfigurationValues({
                    inputs,
                })
            }
        },

        duplicate: async () => {
            if (values.hogFunction) {
                const newConfig = {
                    ...values.configuration,
                    name: `${values.configuration.name} (copy)`,
                }
                const originalTemplate = values.hogFunction.template?.id ?? 'new'
                router.actions.push(hogFunctionNewUrl(newConfig.type, originalTemplate), undefined, {
                    configuration: newConfig,
                })
            }
        },
        duplicateFromTemplate: async () => {
            if (values.hogFunction?.template) {
                const newConfig = {
                    ...values.hogFunction.template,
                }
                router.actions.push(hogFunctionNewUrl(newConfig.type, newConfig.id), undefined, {
                    configuration: newConfig,
                })
            }
        },
        resetToTemplate: async () => {
            const template = values.hogFunction?.template ?? values.template
            if (template) {
                const config = templateToConfiguration(template)

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
            const { id, name, type, template } = values.hogFunction
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/hog_functions`,
                object: {
                    id,
                    name,
                },
                callback(undo) {
                    if (undo) {
                        router.actions.replace(hogFunctionUrl(type, id, template?.id))
                    }
                },
            })

            router.actions.replace(hogFunctionUrl(type, undefined, template?.id))
        },

        persistForUnload: () => {
            actions.setUnsavedConfiguration(values.configuration)
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
        } else if (props.id && props.id !== 'new') {
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

    subscriptions(({ props, actions, cache }) => ({
        hogFunction: (hogFunction) => {
            if (hogFunction && props.templateId) {
                // Catch all for any scenario where we need to redirect away from the template to the actual hog function

                cache.disabledBeforeUnload = true
                router.actions.replace(hogFunctionUrl(hogFunction.type, hogFunction.id, hogFunction.template.id))
            }
        },
        sparklineQuery: async (sparklineQuery) => {
            if (sparklineQuery) {
                actions.sparklineQueryChanged(sparklineQuery)
            }
        },
        personsCountQuery: async (personsCountQuery) => {
            if (personsCountQuery) {
                actions.personsCountQueryChanged(personsCountQuery)
            }
        },
    })),

    beforeUnload(({ values, cache }) => ({
        enabled: (newLocation?: CombinedLocation) => {
            if (cache.disabledBeforeUnload || values.unsavedConfiguration || !values.configurationChanged) {
                return false
            }

            // the oldRoute includes the project id, so we remove it for comparison
            const oldRoute = router.values.location.pathname.replace(/\/project\/\d+/, '').split('/')
            const newRoute = newLocation?.pathname.replace(/\/project\/\d+/, '').split('/')

            if (!newRoute || newRoute.length !== oldRoute.length) {
                return true
            }

            for (let i = 0; i < oldRoute.length - 1; i++) {
                if (oldRoute[i] !== newRoute[i]) {
                    return true
                }
            }

            const possibleMenuIds: string[] = [PipelineNodeTab.Configuration, PipelineNodeTab.Testing]
            if (
                !(
                    possibleMenuIds.includes(newRoute[newRoute.length - 1]) &&
                    possibleMenuIds.includes(oldRoute[newRoute.length - 1])
                )
            ) {
                return true
            }

            return false
        },
        message: 'Changes you made will be discarded.',
        onConfirm: () => {
            cache.disabledBeforeUnload = true
        },
    })),
])
