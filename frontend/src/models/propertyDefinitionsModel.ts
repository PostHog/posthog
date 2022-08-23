import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import {
    BreakdownKeyType,
    PropertyDefinition,
    PropertyDefinitionState,
    PropertyFilterValue,
    PropertyType,
    SelectOption,
} from '~/types'
import type { propertyDefinitionsModelType } from './propertyDefinitionsModelType'
import { dayjs } from 'lib/dayjs'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { colonDelimitedDuration } from 'lib/utils'
import { combineUrl } from 'kea-router'

export interface PropertySelectOption extends SelectOption {
    is_numerical?: boolean
}

// Null means loading
export type PropertyDefinitionStorage = Record<string, PropertyDefinition | PropertyDefinitionState>

// List of property definitions that are calculated on the backend. These
// are valid properties that do not exist on events.
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

export type FormatPropertyValueForDisplayFunction = (
    propertyName?: string,
    valueToFormat?: PropertyFilterValue
) => string | string[] | null

export const propertyDefinitionsModel = kea<propertyDefinitionsModelType>([
    path(['models', 'propertyDefinitionsModel']),
    actions({
        loadPropertyDefinitions: (properties: string[]) => ({ properties }),
        updatePropertyDefinition: (propertyDefinition: PropertyDefinition) => ({ propertyDefinition }),
        updatePropertyDefinitions: (propertyDefinitions: PropertyDefinition[]) => ({ propertyDefinitions }),
        setPropertyDefinitionStorage: (propertyDefinitions: PropertyDefinitionStorage) => ({ propertyDefinitions }),
    }),
    reducers({
        propertyDefinitionStorage: [
            {} as PropertyDefinitionStorage,
            {
                setPropertyDefinitionStorage: (_, { propertyDefinitions }) => propertyDefinitions,
                updatePropertyDefinition: (state, { propertyDefinition }) => ({
                    ...state,
                    [propertyDefinition.name]: propertyDefinition,
                }),
                updatePropertyDefinitions: (state, { propertyDefinitions }) => ({
                    ...state,
                    ...Object.fromEntries(propertyDefinitions.map((p) => [p.name, p])),
                }),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadPropertyDefinitions: async ({ properties }) => {
            const { propertyDefinitionStorage } = values

            let fetchNewProperties = false
            const propertiesToFetch: PropertyDefinitionStorage = {}
            for (const property of properties) {
                if (
                    !(property in propertyDefinitionStorage) ||
                    propertyDefinitionStorage[property] === PropertyDefinitionState.Error
                ) {
                    fetchNewProperties = true
                    propertiesToFetch[property] = PropertyDefinitionState.Pending
                }
            }

            // nothing more to do
            if (!fetchNewProperties) {
                return
            }

            actions.setPropertyDefinitionStorage({ ...propertyDefinitionStorage, ...propertiesToFetch })

            try {
                const url = 'api/projects/@current/property_definitions/?limit=5000'
                const propertyDefinitions = await api.get(combineUrl(url, { properties: properties.join(',') }).url)
                const newProperties: PropertyDefinitionStorage = { ...values.propertyDefinitionStorage }
                for (const propertyDefinition of propertyDefinitions.results) {
                    newProperties[propertyDefinition.name] = propertyDefinition
                }
                for (const property of properties) {
                    if (newProperties[property] === PropertyDefinitionState.Loading) {
                        newProperties[property] = PropertyDefinitionState.Missing
                    }
                }
                actions.setPropertyDefinitionStorage(newProperties)
            } catch (e) {
                const newProperties: PropertyDefinitionStorage = { ...values.propertyDefinitionStorage }
                for (const property of properties) {
                    if (newProperties[property] === PropertyDefinitionState.Loading) {
                        newProperties[property] = PropertyDefinitionState.Error
                    }
                }
                actions.setPropertyDefinitionStorage(newProperties)
            }
        },
    })),
    selectors(({ actions }) => ({
        propertyStorageLoading: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): boolean =>
                Object.values(propertyDefinitionStorage).some((p) => p === PropertyDefinitionState.Loading),
        ],
        propertyDefinitions: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): PropertyDefinition[] => [
                ...(Object.values(propertyDefinitionStorage).filter(
                    (value) => typeof value === 'object'
                ) as PropertyDefinition[]),
                ...localPropertyDefinitions,
            ],
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
            (propertyDefinitions): ((s: TaxonomicFilterValue) => string | null) =>
                (propertyName: TaxonomicFilterValue) => {
                    // if the model hasn't already cached this definition, will fall back to original display type
                    const match = propertyDefinitions.find((pd) => pd.name === propertyName)
                    return match?.property_type ?? null
                },
        ],
        getPropertyDefinition: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): ((s: TaxonomicFilterValue) => PropertyDefinition | null) =>
                (propertyName: TaxonomicFilterValue) =>
                    typeof propertyDefinitionStorage[propertyName] === 'object'
                        ? (propertyDefinitionStorage[propertyName] as PropertyDefinition)
                        : null,
        ],
        formatPropertyValueForDisplay: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage): FormatPropertyValueForDisplayFunction => {
                return (propertyName?: BreakdownKeyType, valueToFormat?: PropertyFilterValue | undefined) => {
                    if (valueToFormat === null || valueToFormat === undefined) {
                        return null
                    }

                    // first time we see this, schedule a fetch
                    if (typeof propertyName === 'string' && !(propertyName in propertyDefinitionStorage)) {
                        window.setTimeout(() => actions.loadPropertyDefinitions([propertyName]), 0)
                    }

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
    })),
])
