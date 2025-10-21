import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api, { ApiMethodOptions, CountedPaginatedResponse } from 'lib/api'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { captureTimeToSeeData } from 'lib/internalMetrics'
import { colonDelimitedDuration } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { teamLogic } from 'scenes/teamLogic'

import {
    BreakdownKeyType,
    GroupTypeIndex,
    PropertyDefinition,
    PropertyDefinitionState,
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyType,
} from '~/types'

import { groupsModel } from './groupsModel'
import type { propertyDefinitionsModelType } from './propertyDefinitionsModelType'

export type PropertyDefinitionStorage = Record<string, PropertyDefinition | PropertyDefinitionState>

/** These property filter types get suggestions based on events – filter value suggestions look just a few days back. */
export const PROPERTY_FILTER_TYPES_WITH_TEMPORAL_SUGGESTIONS = [PropertyFilterType.Event, PropertyFilterType.Feature]
/** These property filter types get suggestions based on persons and groups – filter value suggestions ignore time. */
export const PROPERTY_FILTER_TYPES_WITH_ALL_TIME_SUGGESTIONS = [
    PropertyFilterType.Person,
    PropertyFilterType.Group,
    // As of August 2024, session property values also aren't time-sensitive, but this may change
    // (see RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER)
    PropertyFilterType.Session,
]

// List of property definitions that are calculated on the backend. These
// are valid properties that do not exist on events.
const localProperties: PropertyDefinitionStorage = {
    'event/$session_duration': {
        id: '$session_duration',
        name: '$session_duration',
        description: 'Duration of the session',
        is_numerical: true,
        is_seen_on_filtered_events: false,
        property_type: PropertyType.Duration,
    },
    'session/snapshot_source': {
        id: 'snapshot_source',
        name: 'snapshot_source',
        description: 'Platform session occurred on',
        is_numerical: false,
        is_seen_on_filtered_events: false,
        property_type: PropertyType.Selector,
    },
    'resource/assignee': {
        id: 'assignee',
        name: 'assignee',
        description: 'User or role assigned to a resource',
        property_type: PropertyType.Assignee,
    },
    'resource/first_seen': {
        id: 'first_seen',
        name: 'first_seen',
        description: 'The first time the resource was seen',
        property_type: PropertyType.DateTime,
    },
}

const localOptions: Record<string, PropValue[]> = {
    'session/snapshot_source': [
        { id: 0, name: 'web' },
        { id: 1, name: 'mobile' },
    ],
    'log_entry/level': [
        { id: 0, name: 'info' },
        { id: 1, name: 'warn' },
        { id: 2, name: 'error' },
    ],
}

export type FormatPropertyValueForDisplayFunction = (
    propertyName?: BreakdownKeyType,
    valueToFormat?: PropertyFilterValue,
    type?: PropertyDefinitionType,
    groupTypeIndex?: GroupTypeIndex | null
) => string | string[] | null

/** Update cached property definition metadata */
export const updatePropertyDefinitions = (propertyDefinitions: PropertyDefinitionStorage): void => {
    propertyDefinitionsModel.findMounted()?.actions.updatePropertyDefinitions(propertyDefinitions)
}

export type PropValue = {
    id?: number
    name?: string | boolean
}

export type Option = {
    label?: string
    name?: string
    status?: 'loading' | 'loaded'
    allowCustomValues?: boolean
    values?: PropValue[]
}

const getPropertyKey = (
    type: PropertyDefinitionType,
    propertyName?: BreakdownKeyType,
    groupTypeIndex?: number | null
): string => {
    if (type === PropertyDefinitionType.Group) {
        return `${type}/${groupTypeIndex}/${propertyName}`
    }
    return `${type}/${propertyName}`
}

/** Schedules an immediate background task, that fetches property definitions after a 10ms debounce. Returns the property sync if already found. */
const checkOrLoadPropertyDefinition = (
    propertyName: BreakdownKeyType | undefined,
    definitionType: PropertyDefinitionType,
    propertyDefinitionStorage: PropertyDefinitionStorage,
    groupTypeIndex?: number | null
): PropertyDefinition | null => {
    const key = getPropertyKey(definitionType, propertyName, groupTypeIndex)
    if (typeof propertyName === 'string' && !(key in propertyDefinitionStorage)) {
        // first time we see this, schedule a fetch
        window.setTimeout(
            () =>
                propertyDefinitionsModel
                    .findMounted()
                    ?.actions.loadPropertyDefinitions([propertyName], definitionType, groupTypeIndex),
            0
        )
    }
    const cachedResponse = propertyDefinitionStorage[key]
    if (typeof cachedResponse === 'object') {
        return cachedResponse
    }
    return null
}

const constructValuesEndpoint = (
    endpoint: string | undefined,
    teamId: number,
    type: PropertyDefinitionType,
    propertyKey: string,
    eventNames: string[] | undefined,
    newInput: string | undefined,
    properties?: { key: string; values: string | string[] }[]
): string => {
    let basePath: string

    if (type === PropertyDefinitionType.Session) {
        basePath = `api/environments/${teamId}/${type}s/values`
    } else if (type === PropertyDefinitionType.FlagValue) {
        // FlagValue is project-scoped, so use the project-scoped endpoint
        basePath = `api/projects/${teamId}/${type}/values`
    } else {
        basePath = `api/${type}/values`
    }

    const path = endpoint ? endpoint : basePath + `?key=${encodeURIComponent(propertyKey)}`

    let eventParams = ''
    for (const eventName of eventNames || []) {
        eventParams += `&event_name=${eventName}`
    }

    // Add property filters
    if (properties?.length) {
        for (const prop of properties) {
            const values = Array.isArray(prop.values) ? prop.values : [prop.values]
            eventParams += `&properties_${prop.key}=${encodeURIComponent(JSON.stringify(values))}`
        }
    }

    return path + (newInput ? '&value=' + encodeURIComponent(newInput) : '') + eventParams
}

export const propertyDefinitionsModel = kea<propertyDefinitionsModelType>([
    path(['models', 'propertyDefinitionsModel']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], groupsModel, ['groupTypes']],
    })),
    actions({
        // public
        loadPropertyDefinitions: (
            propertyKeys: string[],
            type: PropertyDefinitionType,
            groupTypeIndex?: number | null
        ) => ({ propertyKeys, type, groupTypeIndex }),
        updatePropertyDefinitions: (propertyDefinitions: PropertyDefinitionStorage) => ({
            propertyDefinitions,
        }),
        // PropertyValue
        loadPropertyValues: (payload: {
            endpoint: string | undefined
            type: PropertyDefinitionType
            newInput: string | undefined
            propertyKey: string
            eventNames?: string[]
            properties?: { key: string; values: string | string[] }[]
        }) => payload,
        setOptionsLoading: (key: string) => ({ key }),
        setOptions: (key: string, values: PropValue[], allowCustomValues: boolean) => ({
            key,
            values,
            allowCustomValues,
        }),
        // internal
        fetchAllPendingDefinitions: true,
        abortAnyRunningQuery: true,
    }),
    reducers({
        rawPropertyDefinitionStorage: [
            { ...localProperties } as PropertyDefinitionStorage,
            {
                updatePropertyDefinitions: (state, { propertyDefinitions }) => {
                    return {
                        ...state,
                        ...propertyDefinitions,
                    }
                },
            },
        ],
        options: [
            {} as Record<string, Option>,
            {
                setOptionsLoading: (state, { key }) => ({ ...state, [key]: { ...state[key], status: 'loading' } }),
                setOptions: (state, { key, values, allowCustomValues }) => ({
                    ...state,
                    [key]: {
                        values: Array.from(new Set(values)),
                        status: 'loaded',
                        allowCustomValues,
                    },
                }),
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadPropertyDefinitions: async ({ propertyKeys, type, groupTypeIndex }) => {
            const { rawPropertyDefinitionStorage } = values

            const pendingStateUpdate: PropertyDefinitionStorage = {}
            for (const propertyKey of propertyKeys) {
                const key = getPropertyKey(type, propertyKey, groupTypeIndex)
                if (
                    !(key in rawPropertyDefinitionStorage) ||
                    rawPropertyDefinitionStorage[key] === PropertyDefinitionState.Error
                ) {
                    pendingStateUpdate[key] = PropertyDefinitionState.Pending
                }
            }

            // nothing new to do
            if (Object.keys(pendingStateUpdate).length === 0) {
                return
            }

            // set all requested properties as `PropertyDefinitionState.Pending`
            actions.updatePropertyDefinitions(pendingStateUpdate)
            // run the next part of this chain
            actions.fetchAllPendingDefinitions()
        },
        fetchAllPendingDefinitions: async (_, breakpoint) => {
            // take 10ms to debounce property definition requests, preventing a lot of small queries
            await breakpoint(10)
            if (values.pendingProperties.length === 0) {
                return
            }
            // take the first 50 pending properties to avoid the 4k query param length limit
            const allPending = values.pendingProperties.slice(0, 50)
            const pendingByType: Record<
                'event' | 'person' | 'group/0' | 'group/1' | 'group/2' | 'group/3' | 'group/4' | 'session',
                string[]
            > = {
                event: [],
                person: [],
                'group/0': [],
                'group/1': [],
                'group/2': [],
                'group/3': [],
                'group/4': [],
                session: [],
            }
            for (const key of allPending) {
                let [type, ...rest] = key.split('/')

                if (type === 'group') {
                    type = `${type}/${rest[0]}`
                    rest = rest.slice(1)
                }
                if (!(type in pendingByType)) {
                    throw new Error(`Unknown property definition type: ${type}`)
                }
                pendingByType[type].push(rest.join('/'))
            }
            try {
                // since this is a unique query, there is no breakpoint here to prevent out of order replies
                const newProperties: PropertyDefinitionStorage = {}
                for (const [type, pending] of Object.entries(pendingByType)) {
                    if (pending.length === 0) {
                        continue
                    }
                    // set them all as PropertyDefinitionState.Loading
                    actions.updatePropertyDefinitions(
                        Object.fromEntries(pending.map((key) => [`${type}/${key}`, PropertyDefinitionState.Loading]))
                    )

                    let queryParams = {
                        type: type as PropertyDefinitionType,
                        group_type_index: null as string | null,
                    }
                    if (type.startsWith('group')) {
                        queryParams = {
                            type: PropertyDefinitionType.Group,
                            group_type_index: type.split('/')[1],
                        }
                    }

                    // and then fetch them
                    let propertyDefinitions: CountedPaginatedResponse<PropertyDefinition>
                    if (type === 'session') {
                        propertyDefinitions = await api.sessions.propertyDefinitions({
                            properties: pending,
                        })
                    } else {
                        propertyDefinitions = await api.propertyDefinitions.list({
                            properties: pending,
                            ...queryParams,
                        })
                    }

                    for (const propertyDefinition of propertyDefinitions.results) {
                        newProperties[`${type}/${propertyDefinition.name}`] = propertyDefinition
                    }
                    // mark those that were not returned as PropertyDefinitionState.Missing
                    for (const property of pending) {
                        const key = `${type}/${property}`
                        if (
                            !(key in newProperties) &&
                            values.rawPropertyDefinitionStorage[key] === PropertyDefinitionState.Loading
                        ) {
                            newProperties[key] = PropertyDefinitionState.Missing
                        }
                    }
                    actions.updatePropertyDefinitions(newProperties)
                }
            } catch {
                const newProperties: PropertyDefinitionStorage = {}
                for (const [type, pending] of Object.entries(pendingByType)) {
                    for (const property of pending) {
                        const key = `${type}/${property}`
                        if (values.rawPropertyDefinitionStorage[key] === PropertyDefinitionState.Loading) {
                            newProperties[key] = PropertyDefinitionState.Error
                        }
                    }
                }
                actions.updatePropertyDefinitions(newProperties)
            }

            // break if something is already happening
            breakpoint()
            // otherwise rerun if any properties remain pending
            if (values.pendingProperties.length > 0) {
                actions.fetchAllPendingDefinitions()
            }
        },

        loadPropertyValues: async ({ endpoint, type, newInput, propertyKey, eventNames, properties }, breakpoint) => {
            if (['cohort'].includes(type)) {
                return
            }
            if (!propertyKey || values.currentTeamId === null) {
                return
            }

            if (localOptions[getPropertyKey(type, propertyKey)]) {
                actions.setOptions(propertyKey, localOptions[getPropertyKey(type, propertyKey)], false)
                return
            }

            const start = performance.now()

            await breakpoint(300)
            actions.setOptionsLoading(propertyKey)
            actions.abortAnyRunningQuery()

            cache.abortController = new AbortController()
            const methodOptions: ApiMethodOptions = {
                signal: cache.abortController.signal,
            }

            const propValues: PropValue[] = await api.get(
                constructValuesEndpoint(
                    endpoint,
                    values.currentTeamId,
                    type,
                    propertyKey,
                    eventNames,
                    newInput,
                    properties
                ),
                methodOptions
            )
            breakpoint()
            actions.setOptions(propertyKey, propValues, type !== PropertyDefinitionType.FlagValue)
            cache.abortController = null

            await captureTimeToSeeData(teamLogic.values.currentTeamId, {
                type: 'property_values_load',
                context: 'filters',
                action: type,
                primary_interaction_id: '',
                status: 'success',
                time_to_see_data_ms: Math.floor(performance.now() - start),
                api_response_bytes: 0,
            })
        },

        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
    })),
    selectors({
        pendingProperties: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): string[] =>
                Object.keys(propertyDefinitionStorage).filter(
                    (key) => propertyDefinitionStorage[key] === PropertyDefinitionState.Pending
                ),
        ],
        propertyDefinitionsByType: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): ((type: string, groupTypeIndex?: number | null) => PropertyDefinition[]) => {
                return (type, groupTypeIndex) => {
                    const keyPrefix = type === 'group' ? `${type}/${groupTypeIndex}/` : `${type}/`

                    return Object.entries(propertyDefinitionStorage ?? {})
                        .filter(([key, value]) => key.startsWith(keyPrefix) && typeof value === 'object')
                        .map(([, value]) => value as PropertyDefinition)
                }
            },
        ],
        propertyDefinitionStorage: [
            (s) => [s.rawPropertyDefinitionStorage, s.eventMetadataPropertyDefinitions],
            (rawPropertyDefinitionStorage, eventMetadataPropertyDefinitions): PropertyDefinitionStorage => {
                const metadataDefinitions = Object.fromEntries(
                    eventMetadataPropertyDefinitions.map((definition) => [
                        `${PropertyDefinitionType.EventMetadata}/${definition.id}`,
                        definition,
                    ])
                )
                return {
                    ...rawPropertyDefinitionStorage,
                    ...metadataDefinitions,
                }
            },
        ],
        getPropertyDefinition: [
            (s) => [s.propertyDefinitionStorage],
            (
                    propertyDefinitionStorage
                ): ((
                    s: TaxonomicFilterValue,
                    type: PropertyDefinitionType,
                    groupTypeIndex?: number
                ) => PropertyDefinition | null) =>
                (
                    propertyName: TaxonomicFilterValue,
                    type: PropertyDefinitionType,
                    groupTypeIndex?: number
                ): PropertyDefinition | null => {
                    if (
                        !propertyName ||
                        (type === PropertyDefinitionType.Group &&
                            (groupTypeIndex === undefined || groupTypeIndex === null))
                    ) {
                        return null
                    }
                    return checkOrLoadPropertyDefinition(propertyName, type, propertyDefinitionStorage, groupTypeIndex)
                },
        ],
        describeProperty: [
            (s) => [s.propertyDefinitionStorage],
            (
                    propertyDefinitionStorage
                ): ((
                    s: TaxonomicFilterValue,
                    type: PropertyDefinitionType,
                    groupTypeIndex?: number
                ) => string | null) =>
                (propertyName: TaxonomicFilterValue, type: PropertyDefinitionType, groupTypeIndex?: number) => {
                    if (
                        !propertyName ||
                        (type === PropertyDefinitionType.Group &&
                            (groupTypeIndex === undefined || groupTypeIndex === null))
                    ) {
                        return null
                    }
                    return (
                        checkOrLoadPropertyDefinition(propertyName, type, propertyDefinitionStorage, groupTypeIndex)
                            ?.property_type ?? null
                    )
                },
        ],
        formatPropertyValueForDisplay: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): FormatPropertyValueForDisplayFunction => {
                return (
                    propertyName?: BreakdownKeyType,
                    valueToFormat?: PropertyFilterValue | undefined,
                    type?: PropertyDefinitionType,
                    groupTypeIndex?: number | null
                ) => {
                    if (
                        valueToFormat === null ||
                        valueToFormat === undefined ||
                        (type === PropertyDefinitionType.Group &&
                            (groupTypeIndex === undefined || groupTypeIndex === null))
                    ) {
                        return null
                    }
                    const propertyDefinition: PropertyDefinition | null = checkOrLoadPropertyDefinition(
                        propertyName,
                        type ?? PropertyDefinitionType.Event,
                        propertyDefinitionStorage,
                        groupTypeIndex
                    )
                    const arrayOfPropertyValues = Array.isArray(valueToFormat) ? valueToFormat : [valueToFormat]

                    const formattedValues = arrayOfPropertyValues.map((_propertyValue) => {
                        const propertyValue: string | null = String(_propertyValue)

                        if (propertyDefinition?.property_type === 'DateTime') {
                            const unixTimestampMilliseconds = /^\d{13}$/
                            const unixTimestampSeconds = /^\d{10}(\.\d*)?$/

                            // dayjs parses unix timestamps differently
                            // depending on if they're in seconds or milliseconds
                            if (propertyValue?.match(unixTimestampSeconds)) {
                                const numericalTimestamp = Number.parseFloat(propertyValue)
                                return dayjs.unix(numericalTimestamp).tz().format('YYYY-MM-DD hh:mm:ss')
                            } else if (propertyValue?.match(unixTimestampMilliseconds)) {
                                const numericalTimestamp = Number.parseInt(propertyValue)
                                return dayjs(numericalTimestamp).tz().format('YYYY-MM-DD hh:mm:ss')
                            }
                        } else if (propertyDefinition?.property_type === PropertyType.Duration) {
                            const numericalDuration = Number.parseFloat(propertyValue)
                            return isNaN(numericalDuration) ? propertyValue : colonDelimitedDuration(numericalDuration)
                        }

                        return propertyValue
                    })

                    // formattedValues is always an array after normalising above
                    // but if the caller sent a single value we should return one
                    return Array.isArray(valueToFormat) ? formattedValues : formattedValues[0]
                }
            },
        ],
        eventMetadataPropertyDefinitions: [
            (s) => [s.groupTypes],
            (groupTypes) => {
                const definitions = [
                    {
                        id: 'event',
                        name: 'event',
                        property_type: PropertyType.String,
                        type: PropertyDefinitionType.EventMetadata,
                    },
                    {
                        id: 'timestamp',
                        name: 'timestamp',
                        property_type: PropertyType.DateTime,
                        type: PropertyDefinitionType.EventMetadata,
                    },
                    {
                        id: 'distinct_id',
                        name: 'distinct_id',
                        property_type: PropertyType.String,
                        type: PropertyDefinitionType.EventMetadata,
                    },
                    {
                        id: 'person_id',
                        name: 'person_id',
                        property_type: PropertyType.String,
                        type: PropertyDefinitionType.EventMetadata,
                    },
                    {
                        id: 'person_mode',
                        name: 'person_mode',
                        property_type: PropertyType.String,
                        type: PropertyDefinitionType.EventMetadata,
                    },
                ] as PropertyDefinition[]
                for (const [groupTypeIndex, groupType] of groupTypes) {
                    const column = `$group_${groupTypeIndex}`
                    definitions.push({
                        id: column,
                        name: groupType.name_singular || groupType.group_type,
                        property_type: PropertyType.String,
                        type: PropertyDefinitionType.EventMetadata,
                    })
                }
                return definitions
            },
        ],
    }),
    permanentlyMount(),
])
