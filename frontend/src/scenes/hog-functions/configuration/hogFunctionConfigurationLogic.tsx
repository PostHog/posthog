import { lemonToast } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { actions, afterMount, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { LiquidRenderer } from 'lib/utils/liquid'
import posthog from 'posthog-js'
import { asDisplay } from 'scenes/persons/person-utils'
import { pipelineNodeLogic } from 'scenes/pipeline/pipelineNodeLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { performQuery } from '~/queries/query'
import { DataTableNode, EventsNode, EventsQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { escapePropertyAsHogQLIdentifier, hogql, setLatestVersionsOnQuery } from '~/queries/utils'
import {
    AnyPropertyFilter,
    AvailableFeature,
    BaseMathType,
    ChartDisplayType,
    CyclotronJobFiltersType,
    CyclotronJobInputSchemaType,
    CyclotronJobInputType,
    CyclotronJobInvocationGlobals,
    CyclotronJobInvocationGlobalsWithInputs,
    EventType,
    FilterLogicalOperator,
    HogFunctionConfigurationContextId,
    HogFunctionConfigurationType,
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

import { EmailTemplate } from '../email-templater/emailTemplaterLogic'
import { eventToHogFunctionContextId } from '../sub-templates/sub-templates'
import type { hogFunctionConfigurationLogicType } from './hogFunctionConfigurationLogicType'

export interface HogFunctionConfigurationLogicProps {
    logicKey?: string
    templateId?: string | null
    id?: string | null
}

export const EVENT_VOLUME_DAILY_WARNING_THRESHOLD = 1000
const UNSAVED_CONFIGURATION_TTL = 1000 * 60 * 5
export const HOG_CODE_SIZE_LIMIT = 100 * 1024 // 100KB to match backend limit

const VALIDATION_RULES = {
    SITE_DESTINATION_REQUIRES_MAPPINGS: (data: HogFunctionConfigurationType) =>
        data.type === 'site_destination' && (!data.mappings || data.mappings.length === 0)
            ? 'You must add at least one mapping'
            : undefined,
    INTERNAL_DESTINATION_REQUIRES_FILTERS: (data: HogFunctionConfigurationType) =>
        data.type === 'internal_destination' && data.filters?.events?.length === 0
            ? 'You must choose a filter'
            : undefined,
} as const

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
export const TYPES_WITH_SPARKLINE: HogFunctionTypeType[] = ['destination', 'site_destination', 'transformation']
export const TYPES_WITH_VOLUME_WARNING: HogFunctionTypeType[] = ['destination', 'site_destination']

export function sanitizeConfiguration(data: HogFunctionConfigurationType): HogFunctionConfigurationType {
    function sanitizeInputs(data: HogFunctionMappingType): Record<string, CyclotronJobInputType> {
        const sanitizedInputs: Record<string, CyclotronJobInputType> = {}
        data.inputs_schema?.forEach((inputSchema) => {
            const templatingEnabled = inputSchema.templating ?? true
            const input = data.inputs?.[inputSchema.key]
            const secret = input?.secret
            let value = input?.value

            if (secret) {
                // If set this means we haven't changed the value
                sanitizedInputs[inputSchema.key] = {
                    value: '********', // Don't send the actual value
                    secret: true,
                }
                return
            }

            if (inputSchema.type === 'json' && typeof value === 'string') {
                try {
                    value = JSON.parse(value)
                } catch {
                    // Ignore
                }
            }

            sanitizedInputs[inputSchema.key] = {
                value: value,
                templating: templatingEnabled ? input?.templating ?? 'hog' : undefined,
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
    function getInputs(inputs_schema?: CyclotronJobInputSchemaType[] | null): Record<string, CyclotronJobInputType> {
        const inputs: Record<string, CyclotronJobInputType> = {}
        inputs_schema?.forEach((schema) => {
            if (schema.default !== undefined) {
                inputs[schema.key] = { value: schema.default }
            }
        })
        return inputs
    }

    function getMappingInputs(
        inputs_schema?: CyclotronJobInputSchemaType[] | null
    ): Record<string, CyclotronJobInputType> {
        const inputs: Record<string, CyclotronJobInputType> = {}
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
        description: typeof template.description === 'string' ? template.description : '',
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
        enabled: true,
    }
}

export function convertToHogFunctionInvocationGlobals(
    event: EventType,
    person: PersonType
): CyclotronJobInvocationGlobals {
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

export type SparklineData = {
    data: { name: string; values: number[]; color: string }[]
    count: number
    labels: string[]
    warning?: string
}

// Helper function to check if code might return null/undefined
export function mightDropEvents(code: string): boolean {
    const sanitizedCode = code
        .replace(/\/\*[\s\S]*?\*\/|\/\/.*/g, '') // Remove comments
        .replace(/\s+/g, ' ') // Collapse whitespace
        .trim()

    if (!sanitizedCode) {
        return false
    }

    // Direct null/undefined returns
    if (
        sanitizedCode.includes('return null') ||
        sanitizedCode.includes('return undefined') ||
        /\breturn\b\s*;/.test(sanitizedCode) ||
        /\breturn\b\s*$/.test(sanitizedCode) ||
        /\bif\s*\([^)]*\)\s*\{\s*\breturn\s+(null|undefined)\b/.test(sanitizedCode)
    ) {
        return true
    }

    // Check for variables set to null/undefined that are also returned
    const nullVarMatch = code.match(/\blet\s+(\w+)\s*:?=\s*(null|undefined)/g)
    if (nullVarMatch) {
        // Extract variable names
        const nullVars = nullVarMatch
            .map((match) => {
                return match.match(/\blet\s+(\w+)/)?.[1]
            })
            .filter(Boolean)

        // Check if any of these variables are returned
        for (const varName of nullVars) {
            if (new RegExp(`\\breturn\\s+${varName}\\b`).test(code)) {
                return true
            }
        }
    }

    return false
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
            featureFlagLogic,
            ['featureFlags'],
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
        loadSampleGlobals: (payload?: { eventId?: string }) => ({ eventId: payload?.eventId }),
        setUnsavedConfiguration: (configuration: HogFunctionConfigurationType | null) => ({ configuration }),
        persistForUnload: true,
        setSampleGlobalsError: (error) => ({ error }),
        setSampleGlobals: (sampleGlobals: CyclotronJobInvocationGlobals | null) => ({ sampleGlobals }),
        setShowEventsList: (showEventsList: boolean) => ({ showEventsList }),
        setOldHogCode: (oldHogCode: string) => ({ oldHogCode }),
        setNewHogCode: (newHogCode: string) => ({ newHogCode }),
        clearHogCodeDiff: true,
        reportAIHogFunctionPrompted: true,
        reportAIHogFunctionAccepted: true,
        reportAIHogFunctionRejected: true,
        reportAIHogFunctionPromptOpen: true,
        setOldFilters: (oldFilters: CyclotronJobFiltersType) => ({ oldFilters }),
        setNewFilters: (newFilters: CyclotronJobFiltersType) => ({ newFilters }),
        clearFiltersDiff: true,
        reportAIFiltersPrompted: true,
        reportAIFiltersAccepted: true,
        reportAIFiltersRejected: true,
        reportAIFiltersPromptOpen: true,
        setOldInputs: (oldInputs: CyclotronJobInputSchemaType[]) => ({ oldInputs }),
        setNewInputs: (newInputs: CyclotronJobInputSchemaType[]) => ({ newInputs }),
        clearInputsDiff: true,
        reportAIHogFunctionInputsPrompted: true,
        reportAIHogFunctionInputsAccepted: true,
        reportAIHogFunctionInputsRejected: true,
        reportAIHogFunctionInputsPromptOpen: true,
    }),
    reducers(({ props }) => ({
        sampleGlobals: [
            null as CyclotronJobInvocationGlobals | null,
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
        oldHogCode: [
            null as string | null,
            {
                setOldHogCode: (_, { oldHogCode }) => oldHogCode,
                clearHogCodeDiff: () => null,
            },
        ],
        newHogCode: [
            null as string | null,
            {
                setNewHogCode: (_, { newHogCode }) => newHogCode,
                clearHogCodeDiff: () => null,
            },
        ],
        oldFilters: [
            null as CyclotronJobFiltersType | null,
            {
                setOldFilters: (_, { oldFilters }) => oldFilters,
                clearFiltersDiff: () => null,
            },
        ],
        newFilters: [
            null as CyclotronJobFiltersType | null,
            {
                setNewFilters: (_, { newFilters }) => newFilters,
                clearFiltersDiff: () => null,
            },
        ],
        oldInputs: [
            null as CyclotronJobInputSchemaType[] | null,
            {
                setOldInputs: (_, { oldInputs }) => oldInputs,
                clearInputsDiff: () => null,
            },
        ],
        newInputs: [
            null as CyclotronJobInputSchemaType[] | null,
            {
                setNewInputs: (_, { newInputs }) => newInputs,
                clearInputsDiff: () => null,
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

                    const dbTemplates = !!values.featureFlags[FEATURE_FLAGS.GET_HOG_TEMPLATES_FROM_DB]
                    const res = await api.hogFunctions.getTemplate(props.templateId, dbTemplates)

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
                        type: res.type,
                        enabled: res.enabled,
                    })

                    lemonToast.success('Configuration saved')
                    refreshTreeItem('hog_function/', res.id)

                    return res
                },
            },
        ],

        sparkline: [
            null as null | SparklineData,
            {
                sparklineQueryChanged: async ({ sparklineQuery }, breakpoint) => {
                    if (!TYPES_WITH_SPARKLINE.includes(values.type)) {
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
                    const showVolumeWarning = TYPES_WITH_VOLUME_WARNING.includes(values.type)

                    if (showVolumeWarning) {
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
                        return { data, count: result?.results?.[0]?.count, labels: result?.results?.[0]?.labels }
                    }
                    // For transformations, just show the raw values without warning thresholds
                    const data = [
                        {
                            name: 'Volume',
                            values: dataValues,
                            color: 'success',
                        },
                    ]
                    return {
                        data,
                        count: result?.results?.[0]?.count,
                        labels: result?.results?.[0]?.labels,
                        warning:
                            values.type === 'transformation'
                                ? 'Historical volume may not reflect future volume after transformation is applied.'
                                : undefined,
                    }
                },
            },
        ],

        sampleGlobals: [
            null as CyclotronJobInvocationGlobals | null,
            {
                loadSampleGlobals: async ({ eventId }, breakpoint) => {
                    if (!values.lastEventQuery) {
                        return values.sampleGlobals
                    }
                    const errorMessage =
                        'No events match these filters in the last 30 days. Showing an example $pageview event instead.'
                    try {
                        await breakpoint(values.sampleGlobals === null ? 10 : 1000)
                        let response = await performQuery({
                            ...values.lastEventQuery,
                            properties: eventId
                                ? [
                                      {
                                          type: PropertyFilterType.HogQL,
                                          key: `uuid = '${eventId}'`,
                                      },
                                  ]
                                : undefined,
                        })
                        if (!response?.results?.[0] && values.lastEventSecondQuery) {
                            response = await performQuery({
                                ...values.lastEventSecondQuery,
                                properties: eventId
                                    ? [
                                          {
                                              type: PropertyFilterType.HogQL,
                                              key: `uuid = '${eventId}'`,
                                          },
                                      ]
                                    : undefined,
                            })
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
                                } catch {
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
                    mappings: VALIDATION_RULES.SITE_DESTINATION_REQUIRES_MAPPINGS(data),
                    filters: VALIDATION_RULES.INTERNAL_DESTINATION_REQUIRES_FILTERS(data),
                    ...(values.inputFormErrors as any),
                }
            },
            submit: async (data) => {
                // Check HOG code size immediately before submission
                if (data.hog) {
                    const hogSize = new Blob([data.hog]).size
                    if (hogSize > HOG_CODE_SIZE_LIMIT) {
                        lemonToast.error(
                            `Hog code exceeds maximum size of ${
                                HOG_CODE_SIZE_LIMIT / 1024
                            }KB. Please simplify your code or contact support to increase the limit.`
                        )
                        return
                    }
                }

                const payload: Record<string, any> = sanitizeConfiguration(data)
                // Only sent on create
                payload.template_id = props.templateId || values.hogFunction?.template?.id

                if (!values.hasAddon && values.type !== 'transformation') {
                    // Remove the source field if the user doesn't have the addon (except for transformations)
                    delete payload.hog
                }

                if (!props.id || props.id === 'new') {
                    const type = values.type
                    const typeFolder =
                        type === 'site_app'
                            ? 'Site apps'
                            : type === 'transformation'
                            ? 'Transformations'
                            : type === 'source_webhook'
                            ? 'Sources'
                            : 'Destinations'
                    payload._create_in_folder = `Unfiled/${typeFolder}`
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

        contextId: [
            (s) => [s.configuration],
            (configuration): HogFunctionConfigurationContextId => {
                return eventToHogFunctionContextId(configuration.filters?.events?.[0]?.id)
            },
        ],

        inputFormErrors: [
            (s) => [s.configuration],
            (configuration) => {
                const inputs = configuration.inputs ?? {}
                const inputErrors: Record<string, string> = {}

                configuration.inputs_schema?.forEach((inputSchema) => {
                    const key = inputSchema.key
                    const input = inputs[key]
                    const language = input?.templating ?? 'hog'
                    const value = input?.value
                    if (input?.secret) {
                        // We leave unmodified secret values alone
                        return
                    }

                    const getTemplatingError = (value: string): string | undefined => {
                        if (language === 'liquid' && typeof value === 'string') {
                            try {
                                LiquidRenderer.parse(value)
                            } catch (e: any) {
                                return `Liquid template error: ${e.message}`
                            }
                        }
                    }

                    const addTemplatingError = (value: string): void => {
                        const templatingError = getTemplatingError(value)
                        if (templatingError) {
                            inputErrors[key] = templatingError
                        }
                    }

                    const missing = value === undefined || value === null || value === ''
                    if (inputSchema.required && missing) {
                        inputErrors[key] = 'This field is required'
                    }

                    if (inputSchema.type === 'json' && typeof value === 'string') {
                        try {
                            JSON.parse(value)
                        } catch {
                            inputErrors[key] = 'Invalid JSON'
                        }

                        addTemplatingError(value)
                    }

                    if (inputSchema.type === 'email' && value) {
                        const emailTemplateErrors: Partial<EmailTemplate> = {
                            html: !value.html ? 'HTML is required' : getTemplatingError(value.html),
                            subject: !value.subject ? 'Subject is required' : getTemplatingError(value.subject),
                            // text: !value.text ? 'Text is required' : getTemplatingError(value.text),
                            from: !value.from ? 'From is required' : getTemplatingError(value.from),
                            to: !value.to ? 'To is required' : getTemplatingError(value.to),
                        }

                        const combinedErrors = Object.values(emailTemplateErrors)
                            .filter((v) => !!v)
                            .join(', ')

                        if (combinedErrors) {
                            inputErrors[key] = combinedErrors
                        }
                    }

                    if (inputSchema.type === 'string' && typeof value === 'string') {
                        addTemplatingError(value)
                    }

                    if (inputSchema.type === 'dictionary') {
                        for (const val of Object.values(value ?? {})) {
                            if (typeof val === 'string') {
                                addTemplatingError(val)
                            }
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
            (s) => [s.configuration, s.currentProject, s.groupTypes, s.contextId],
            (configuration, currentProject, groupTypes, contextId): CyclotronJobInvocationGlobals => {
                const currentUrl = window.location.href.split('#')[0]
                const eventId = uuid()
                const personId = uuid()
                const event = {
                    uuid: eventId,
                    distinct_id: uuid(),
                    timestamp: dayjs().toISOString(),
                    elements_chain: '',
                    url: `${window.location.origin}/project/${currentProject?.id}/events/`,
                    ...(contextId === 'error-tracking'
                        ? {
                              event: configuration?.filters?.events?.[0].id || '$error_tracking_issue_created',
                              properties: {
                                  name: 'Test issue',
                                  description: 'This is the issue description',
                              },
                          }
                        : contextId === 'activity-log'
                        ? {
                              event: '$activity_log_entry_created',
                              properties: {
                                  activity: 'created',
                                  scope: 'Insight',
                                  item_id: 'abcdef',
                              },
                          }
                        : {
                              event: '$pageview',
                              properties: {
                                  $current_url: currentUrl,
                                  $browser: 'Chrome',
                                  this_is_an_example_event: true,
                              },
                          }),
                }
                const globals: CyclotronJobInvocationGlobals = {
                    event,
                    person:
                        contextId !== 'error-tracking'
                            ? {
                                  id: personId,
                                  properties: {
                                      email: 'example@posthog.com',
                                  },
                                  name: 'Example person',
                                  url: `${window.location.origin}/person/${personId}`,
                              }
                            : undefined,
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

                if (contextId !== 'error-tracking') {
                    groupTypes.forEach((groupType) => {
                        const id = uuid()
                        globals.groups![groupType.group_type] = {
                            id: id,
                            type: groupType.group_type,
                            index: groupType.group_type_index,
                            url: `${window.location.origin}/groups/${groupType.group_type_index}/${encodeURIComponent(
                                id
                            )}`,
                            properties: {},
                        }
                    })
                }

                return globals
            },
        ],
        sampleGlobalsWithInputs: [
            (s) => [s.sampleGlobals, s.exampleInvocationGlobals, s.configuration],
            (sampleGlobals, exampleInvocationGlobals, configuration): CyclotronJobInvocationGlobalsWithInputs => {
                const inputs: Record<string, any> = {}
                for (const input of configuration?.inputs_schema || []) {
                    inputs[input.key] = input.type
                }

                if (configuration.type === 'source_webhook') {
                    return {
                        request: {
                            body: {},
                            headers: {},
                            ip: '127.0.0.1',
                        },
                        inputs,
                    }
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
                if (!TYPES_WITH_SPARKLINE.includes(type)) {
                    return null
                }
                return setLatestVersionsOnQuery({
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
                })
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
                    const name = escapePropertyAsHogQLIdentifier(groupType.group_type)
                    query.select.push(
                        `tuple(${name}.created_at, ${name}.index, ${name}.key, ${name}.properties, ${name}.updated_at)`
                    )
                })
                return setLatestVersionsOnQuery(query)
            },
            { resultEqualityCheck: equal },
        ],

        eventsDataTableNode: [
            (s) => [s.baseEventsQuery],
            (baseEventsQuery): DataTableNode | null => {
                return baseEventsQuery
                    ? setLatestVersionsOnQuery(
                          {
                              kind: NodeKind.DataTableNode,
                              source: {
                                  ...baseEventsQuery,
                                  select: defaultDataTableColumns(NodeKind.EventsQuery),
                              },
                          },
                          { recursion: false }
                      )
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
        mightDropEvents: [
            (s) => [s.configuration, s.type],
            (configuration, type) => {
                if (type !== 'transformation') {
                    return false
                }
                const hogCode = configuration.hog || ''

                return mightDropEvents(hogCode)
            },
        ],

        currentHogCode: [
            (s) => [s.newHogCode, s.configuration],
            (newHogCode: string | null, configuration: HogFunctionConfigurationType) => {
                return newHogCode ?? configuration.hog ?? ''
            },
        ],

        currentInputs: [
            (s) => [s.newInputs, s.configuration],
            (newInputs: CyclotronJobInputSchemaType[] | null, configuration: HogFunctionConfigurationType) => {
                return newInputs ?? configuration.inputs_schema ?? []
            },
        ],

        inputsDiff: [
            (s) => [s.oldInputs, s.newInputs],
            (oldInputs: CyclotronJobInputSchemaType[] | null, newInputs: CyclotronJobInputSchemaType[] | null) => {
                if (!oldInputs || !newInputs) {
                    return null
                }
                return { oldInputs, newInputs }
            },
        ],

        canLoadSampleGlobals: [
            (s) => [s.lastEventQuery],
            (lastEventQuery) => {
                return !!lastEventQuery
            },
        ],
    })),

    listeners(({ actions, values, cache }) => ({
        reportAIHogFunctionPrompted: () => {
            posthog.capture('ai_hog_function_prompted', { type: values.type })
        },
        reportAIHogFunctionAccepted: () => {
            posthog.capture('ai_hog_function_accepted', { type: values.type })
        },
        reportAIHogFunctionRejected: () => {
            posthog.capture('ai_hog_function_rejected', { type: values.type })
        },
        reportAIHogFunctionPromptOpen: () => {
            posthog.capture('ai_hog_function_prompt_open', { type: values.type })
        },
        reportAIFiltersPrompted: () => {
            posthog.capture('ai_hog_function_filters_prompted', { type: values.type })
        },
        reportAIFiltersAccepted: () => {
            posthog.capture('ai_hog_function_filters_accepted', { type: values.type })
        },
        reportAIFiltersRejected: () => {
            posthog.capture('ai_hog_function_filters_rejected', { type: values.type })
        },
        reportAIFiltersPromptOpen: () => {
            posthog.capture('ai_hog_function_filters_prompt_open', { type: values.type })
        },
        reportAIHogFunctionInputsPrompted: () => {
            posthog.capture('ai_hog_function_inputs_prompted', { type: values.type })
        },
        reportAIHogFunctionInputsAccepted: () => {
            posthog.capture('ai_hog_function_inputs_accepted', { type: values.type })
        },
        reportAIHogFunctionInputsRejected: () => {
            posthog.capture('ai_hog_function_inputs_rejected', { type: values.type })
        },
        reportAIHogFunctionInputsPromptOpen: () => {
            posthog.capture('ai_hog_function_inputs_prompt_open', { type: values.type })
        },
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
                ...cache.configFromUrl,
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
                            }, {} as Record<string, CyclotronJobInputType>),
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
                // TODO: What to do if no template?
                const originalTemplate = values.hogFunction.template!
                router.actions.push(urls.hogFunctionNew(originalTemplate.id), undefined, {
                    configuration: newConfig,
                })
            }
        },
        duplicateFromTemplate: async () => {
            if (values.hogFunction?.template) {
                const newConfig: HogFunctionTemplateType = {
                    ...values.hogFunction.template,
                }
                router.actions.push(urls.hogFunctionNew(values.hogFunction.template.id), undefined, {
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
            const hogFunction = values.hogFunction
            if (!hogFunction) {
                return
            }
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/hog_functions`,
                object: {
                    id: hogFunction.id,
                    name: hogFunction.name,
                },
                callback(undo) {
                    if (undo) {
                        router.actions.replace(urls.hogFunction(hogFunction.id))
                        refreshTreeItem('hog_function/', hogFunction.id)
                    } else {
                        deleteFromTree('hog_function/', hogFunction.id)
                    }
                },
            })

            router.actions.replace(urls.hogFunction(hogFunction.id))
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
            actions.loadTemplate()
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
                router.actions.replace(urls.hogFunction(hogFunction.id))
            }
        },
        sparklineQuery: async (sparklineQuery) => {
            if (sparklineQuery) {
                actions.sparklineQueryChanged(sparklineQuery)
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
