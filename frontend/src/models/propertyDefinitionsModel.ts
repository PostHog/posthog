import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import api, { ApiMethodOptions } from 'lib/api'
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
    PropertyFilterValue,
    PropertyType,
} from '~/types'

import type { propertyDefinitionsModelType } from './propertyDefinitionsModelType'

export type PropertyDefinitionStorage = Record<string, PropertyDefinition | PropertyDefinitionState>

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
}

export type FormatPropertyValueForDisplayFunction = (
    propertyName?: BreakdownKeyType,
    valueToFormat?: PropertyFilterValue,
    type?: PropertyDefinitionType,
    groupTypeIndex?: GroupTypeIndex
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
    values?: PropValue[]
}

const getPropertyKey = (
    type: PropertyDefinitionType,
    propertyName?: BreakdownKeyType,
    groupTypeIndex?: number | null
): string => {
    if (type === PropertyDefinitionType.Group) {
        return `${type}/${groupTypeIndex}/${propertyName}`
    } else {
        return `${type}/${propertyName}`
    }
}

/** Schedules an immediate background task, that fetches property definitions after a 10ms debounce. Returns the property sync if already found. */
const checkOrLoadPropertyDefinition = (
    propertyName: BreakdownKeyType | undefined,
    definitionType: PropertyDefinitionType,
    propertyDefinitionStorage: PropertyDefinitionStorage,
    groupTypeIndex?: number | null
): PropertyDefinition | null => {
    // first time we see this, schedule a fetch
    const key = getPropertyKey(definitionType, propertyName, groupTypeIndex)
    if (typeof propertyName === 'string' && !(key in propertyDefinitionStorage)) {
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

export const propertyDefinitionsModel = kea<propertyDefinitionsModelType>([
    path(['models', 'propertyDefinitionsModel']),
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
        }) => payload,
        setOptionsLoading: (key: string) => ({ key }),
        setOptions: (key: string, values: PropValue[]) => ({ key, values }),
        // internal
        fetchAllPendingDefinitions: true,
        abortAnyRunningQuery: true,
    }),
    reducers({
        propertyDefinitionStorage: [
            { ...localProperties } as PropertyDefinitionStorage,
            {
                updatePropertyDefinitions: (state, { propertyDefinitions }) => ({
                    ...state,
                    ...propertyDefinitions,
                }),
            },
        ],
        options: [
            {} as Record<string, Option>,
            {
                setOptionsLoading: (state, { key }) => ({ ...state, [key]: { ...state[key], status: 'loading' } }),
                setOptions: (state, { key, values }) => ({
                    ...state,
                    [key]: {
                        values: [...Array.from(new Set(values))],
                        status: 'loaded',
                    },
                }),
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadPropertyDefinitions: async ({ propertyKeys, type, groupTypeIndex }) => {
            const { propertyDefinitionStorage } = values

            const pendingStateUpdate: PropertyDefinitionStorage = {}
            for (const propertyKey of propertyKeys) {
                const key = getPropertyKey(type, propertyKey, groupTypeIndex)
                if (
                    !(key in propertyDefinitionStorage) ||
                    propertyDefinitionStorage[key] === PropertyDefinitionState.Error
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
                'event' | 'person' | 'group/0' | 'group/1' | 'group/2' | 'group/3' | 'group/4',
                string[]
            > = {
                event: [],
                person: [],
                'group/0': [],
                'group/1': [],
                'group/2': [],
                'group/3': [],
                'group/4': [],
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
                    const propertyDefinitions = await api.propertyDefinitions.list({
                        properties: pending,
                        ...queryParams,
                    })

                    for (const propertyDefinition of propertyDefinitions.results) {
                        newProperties[`${type}/${propertyDefinition.name}`] = propertyDefinition
                    }
                    // mark those that were not returned as PropertyDefinitionState.Missing
                    for (const property of pending) {
                        const key = `${type}/${property}`
                        if (
                            !(key in newProperties) &&
                            values.propertyDefinitionStorage[key] === PropertyDefinitionState.Loading
                        ) {
                            newProperties[key] = PropertyDefinitionState.Missing
                        }
                    }
                    actions.updatePropertyDefinitions(newProperties)
                }
            } catch (e) {
                const newProperties: PropertyDefinitionStorage = {}
                for (const [type, pending] of Object.entries(pendingByType)) {
                    for (const property of pending) {
                        const key = `${type}/${property}`
                        if (values.propertyDefinitionStorage[key] === PropertyDefinitionState.Loading) {
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

        loadPropertyValues: async ({ endpoint, type, newInput, propertyKey, eventNames }, breakpoint) => {
            if (['cohort', 'session'].includes(type)) {
                return
            }
            if (!propertyKey) {
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

            let eventParams = ''
            for (const eventName of eventNames || []) {
                eventParams += `&event_name=${eventName}`
            }

            const propValues: PropValue[] = await api.get(
                endpoint ||
                    'api/' +
                        type +
                        '/values/?key=' +
                        encodeURIComponent(propertyKey) +
                        (newInput ? '&value=' + encodeURIComponent(newInput) : '') +
                        eventParams,
                methodOptions
            )
            breakpoint()
            actions.setOptions(propertyKey, propValues)
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
    }),
    permanentlyMount(),
])
