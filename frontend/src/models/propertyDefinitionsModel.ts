import { kea } from 'kea'
import api from 'lib/api'
import { PropertyDefinition, PropertyFilterValue, PropertyType, SelectOption } from '~/types'
import type { propertyDefinitionsModelType } from './propertyDefinitionsModelType'
import { dayjs } from 'lib/dayjs'

export interface PropertySelectOption extends SelectOption {
    is_numerical?: boolean
}

export interface PropertyDefinitionStorage {
    count: number
    next: null | string
    results: PropertyDefinition[]
}

const localPropertyDefinitions: PropertyDefinition[] = [
    {
        id: '$session_duration',
        name: '$session_duration',
        description: 'Duration of the session',
        is_numerical: true,
        is_event_property: false,
        property_type: PropertyType.Duration,
    },
]

const normaliseToArray = (
    valueToFormat: Exclude<PropertyFilterValue, null>
): {
    valueWasReceivedAsArray: boolean
    arrayOfPropertyValues: (string | number)[]
} => {
    if (Array.isArray(valueToFormat)) {
        return { arrayOfPropertyValues: valueToFormat, valueWasReceivedAsArray: true }
    } else {
        return { arrayOfPropertyValues: [valueToFormat], valueWasReceivedAsArray: false }
    }
}

export type FormatForDisplayFunction = (
    propertyName: string | undefined,
    valueToFormat: PropertyFilterValue | undefined
) => string | string[] | null

export const propertyDefinitionsModel = kea<propertyDefinitionsModelType>({
    path: ['models', 'propertyDefinitionsModel'],
    actions: () => ({
        loadPropertyDefinitions: (initial = false) => ({ initial }),
        updatePropertyDefinition: (property: PropertyDefinition) => ({ property }),
    }),
    loaders: ({ values }) => ({
        propertyStorage: [
            { results: [], next: null, count: 0 } as PropertyDefinitionStorage,
            {
                loadPropertyDefinitions: async ({ initial }, breakpoint) => {
                    const url = initial
                        ? 'api/projects/@current/property_definitions/?limit=5000'
                        : values.propertyStorage.next
                    if (!url) {
                        throw new Error('Incorrect call to propertyDefinitionsLogic.loadPropertyDefinitions')
                    }
                    const propertyStorage = await api.get(url)
                    breakpoint()
                    return {
                        count: propertyStorage.count,
                        results: [...values.propertyStorage.results, ...propertyStorage.results],
                        next: propertyStorage.next,
                    }
                },
            },
        ],
    }),
    reducers: () => ({
        propertyStorage: [
            { results: [], next: null, count: 0 } as PropertyDefinitionStorage,
            {
                updatePropertyDefinition: (state, { property }) => ({
                    count: state.count,
                    results: state.results.map((p) => (property.id === p.id ? property : p)),
                    next: state.next,
                }),
            },
        ],
    }),
    listeners: ({ actions }) => ({
        loadPropertyDefinitionsSuccess: ({ propertyStorage }) => {
            if (propertyStorage.next) {
                actions.loadPropertyDefinitions()
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadPropertyDefinitions(true)
        },
    }),
    selectors: {
        loaded: [
            // Whether *all* the property definitions are fully loaded
            (s) => [s.propertyStorage, s.propertyStorageLoading],
            (propertyStorage, propertyStorageLoading): boolean => !propertyStorageLoading && !propertyStorage.next,
        ],
        propertyDefinitions: [
            (s) => [s.propertyStorage],
            (propertyStorage): PropertyDefinition[] =>
                propertyStorage.results ? [...localPropertyDefinitions, ...propertyStorage.results] : [],
        ],
        transformedPropertyDefinitions: [
            // Transformed propertyDefinitions to use in `Select` components
            (s) => [s.propertyDefinitions],
            (propertyDefinitions): PropertySelectOption[] =>
                propertyDefinitions.map((property) => ({
                    value: property.name,
                    label: property.name,
                    is_numerical: property.is_numerical,
                })),
        ],
        propertyNames: [
            (s) => [s.propertyDefinitions],
            (propertyDefinitions): string[] => propertyDefinitions.map((definition) => definition.name),
        ],
        numericalPropertyNames: [
            (s) => [s.transformedPropertyDefinitions],
            (transformedPropertyDefinitions): PropertySelectOption[] =>
                transformedPropertyDefinitions.filter((definition) => definition.is_numerical),
        ],
        describeProperty: [
            (s) => [s.propertyDefinitions],
            (propertyDefinitions: PropertyDefinition[]): ((s: string) => string | null) =>
                (propertyName: string) => {
                    // if the model hasn't already cached this definition, will fall back to original display type
                    const match = propertyDefinitions.find((pd) => pd.name === propertyName)
                    return match?.property_type ?? null
                },
        ],
        formatForDisplay: [
            (s) => [s.propertyDefinitions],
            (propertyDefinitions: PropertyDefinition[]): FormatForDisplayFunction => {
                return (propertyName: string | undefined, valueToFormat: PropertyFilterValue | undefined) => {
                    if (valueToFormat === null || valueToFormat === undefined) {
                        return null
                    }

                    const propertyDefinition = propertyName
                        ? propertyDefinitions.find((pd) => pd.name === propertyName)
                        : undefined

                    const { arrayOfPropertyValues, valueWasReceivedAsArray } = normaliseToArray(valueToFormat)

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
                        }

                        return propertyValue
                    })

                    // formattedValues is always an array after normalising above
                    // but if the caller sent a single value we should return one
                    if (valueWasReceivedAsArray) {
                        return formattedValues
                    } else {
                        return formattedValues[0]
                    }
                }
            },
        ],
    },
})
