import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import api, { ApiMethodOptions } from 'lib/api'
import {
    BreakdownKeyType,
    PropertyDefinition,
    PropertyDefinitionState,
    PropertyFilterValue,
    PropertyType,
} from '~/types'
import type { propertyDefinitionsModelType } from './propertyDefinitionsModelType'
import { dayjs } from 'lib/dayjs'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { colonDelimitedDuration } from 'lib/utils'
import { captureTimeToSeeData } from '../lib/internalMetrics'
import { teamLogic } from '../scenes/teamLogic'

export type PropertyDefinitionStorage = Record<string, PropertyDefinition | PropertyDefinitionState>

// List of property definitions that are calculated on the backend. These
// are valid properties that do not exist on events.
const localProperties: PropertyDefinitionStorage = {
    $session_duration: {
        id: '$session_duration',
        name: '$session_duration',
        description: 'Duration of the session',
        is_numerical: true,
        is_event_property: false,
        property_type: PropertyType.Duration,
    },
}

export type FormatPropertyValueForDisplayFunction = (
    propertyName?: BreakdownKeyType,
    valueToFormat?: PropertyFilterValue
) => string | string[] | null

/** Update cached property definition metadata */
export const updatePropertyDefinitions = (
    propertyDefinitions: PropertyDefinition[] | PropertyDefinitionStorage
): void => {
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

/** Schedules an immediate background task, that fetches property definitions after a 10ms debounce */
const checkOrLoadPropertyDefinition = (
    propertyName: BreakdownKeyType | undefined,
    propertyDefinitionStorage: PropertyDefinitionStorage
): void => {
    // first time we see this, schedule a fetch
    if (typeof propertyName === 'string' && !(propertyName in propertyDefinitionStorage)) {
        window.setTimeout(
            () => propertyDefinitionsModel.findMounted()?.actions.loadPropertyDefinitions([propertyName]),
            0
        )
    }
}

export const propertyDefinitionsModel = kea<propertyDefinitionsModelType>([
    path(['models', 'propertyDefinitionsModel']),
    actions({
        // public
        loadPropertyDefinitions: (propertyKeys: string[]) => ({ propertyKeys }),
        updatePropertyDefinitions: (propertyDefinitions: PropertyDefinition[] | PropertyDefinitionStorage) => ({
            propertyDefinitions,
        }),
        // PropertyValue
        loadPropertyValues: (payload: {
            endpoint: string | undefined
            type: string
            newInput: string | undefined
            propertyKey: string
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
                    ...(Array.isArray(propertyDefinitions)
                        ? Object.fromEntries(propertyDefinitions.map((p) => [p.name, p]))
                        : propertyDefinitions),
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
        loadPropertyDefinitions: async ({ propertyKeys }) => {
            const { propertyDefinitionStorage } = values

            const pendingStateUpdate: PropertyDefinitionStorage = {}
            for (const key of propertyKeys) {
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
            const pending = values.pendingProperties.slice(0, 50)
            try {
                // set them all as PropertyDefinitionState.Loading
                actions.updatePropertyDefinitions(
                    Object.fromEntries(pending.map((key) => [key, PropertyDefinitionState.Loading]))
                )
                // and then fetch them
                const propertyDefinitions = await api.propertyDefinitions.list({ properties: pending })

                // since this is a unique query, there is no breakpoint here to prevent out of order replies
                // so save them and don't worry about overriding anything
                const newProperties: PropertyDefinitionStorage = {}
                for (const propertyDefinition of propertyDefinitions.results) {
                    newProperties[propertyDefinition.name] = propertyDefinition
                }
                // mark those that were not returned as PropertyDefinitionState.Missing
                for (const property of pending) {
                    if (
                        !(property in newProperties) &&
                        values.propertyDefinitionStorage[property] === PropertyDefinitionState.Loading
                    ) {
                        newProperties[property] = PropertyDefinitionState.Missing
                    }
                }
                actions.updatePropertyDefinitions(newProperties)
            } catch (e) {
                const newProperties: PropertyDefinitionStorage = {}
                for (const property of pending) {
                    if (values.propertyDefinitionStorage[property] === PropertyDefinitionState.Loading) {
                        newProperties[property] = PropertyDefinitionState.Error
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

        loadPropertyValues: async ({ endpoint, type, newInput, propertyKey }, breakpoint) => {
            if (['cohort', 'session'].includes(type)) {
                return
            }
            if (!propertyKey) {
                return
            }

            const start = performance.now()

            await breakpoint(300)
            const key = propertyKey.split('__')[0]
            actions.setOptionsLoading(propertyKey)
            actions.abortAnyRunningQuery()

            cache.abortController = new AbortController()
            const methodOptions: ApiMethodOptions = {
                signal: cache.abortController.signal,
            }

            const propValues: PropValue[] = await api.get(
                endpoint || 'api/' + type + '/values/?key=' + key + (newInput ? '&value=' + newInput : ''),
                methodOptions
            )
            breakpoint()
            actions.setOptions(propertyKey, propValues)
            cache.abortController = null

            await captureTimeToSeeData(teamLogic.values.currentTeamId, {
                type: 'property_values_load',
                context: 'filters',
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
        propertyDefinitions: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): PropertyDefinition[] =>
                Object.values(propertyDefinitionStorage).filter(
                    (value) => typeof value === 'object'
                ) as PropertyDefinition[],
        ],
        getPropertyDefinition: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): ((s: TaxonomicFilterValue) => PropertyDefinition | null) =>
                (propertyName: TaxonomicFilterValue): PropertyDefinition | null => {
                    checkOrLoadPropertyDefinition(propertyName, propertyDefinitionStorage)
                    return typeof propertyDefinitionStorage[propertyName] === 'object'
                        ? (propertyDefinitionStorage[propertyName] as PropertyDefinition)
                        : null
                },
        ],
        describeProperty: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): ((s: TaxonomicFilterValue) => string | null) =>
                (propertyName: TaxonomicFilterValue) => {
                    checkOrLoadPropertyDefinition(propertyName, propertyDefinitionStorage)
                    // if the model hasn't already cached this definition, will fall back to original display type
                    return typeof propertyDefinitionStorage[propertyName] === 'object'
                        ? (propertyDefinitionStorage[propertyName] as PropertyDefinition).property_type ?? null
                        : null
                },
        ],
        formatPropertyValueForDisplay: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): FormatPropertyValueForDisplayFunction => {
                return (propertyName?: BreakdownKeyType, valueToFormat?: PropertyFilterValue | undefined) => {
                    if (valueToFormat === null || valueToFormat === undefined) {
                        return null
                    }

                    checkOrLoadPropertyDefinition(propertyName, propertyDefinitionStorage)

                    const propertyDefinition: PropertyDefinition | undefined =
                        typeof propertyName === 'string' && typeof propertyDefinitionStorage[propertyName] === 'object'
                            ? (propertyDefinitionStorage[propertyName] as PropertyDefinition)
                            : undefined

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
])
