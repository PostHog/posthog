import { kea } from 'kea'
import api from 'lib/api'
import { PropertyDefinition, SelectOption } from '~/types'
import { propertyDefinitionsModelType } from './propertyDefinitionsModelType'

interface PropertySelectOption extends SelectOption {
    is_numerical?: boolean
}

interface PropertyDefinitionStorage {
    count: number
    next: null | string
    results: PropertyDefinition[]
}

export const propertyDefinitionsModel = kea<
    propertyDefinitionsModelType<PropertyDefinitionStorage, PropertySelectOption>
>({
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
            (propertyStorage): PropertyDefinition[] => propertyStorage.results || [],
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
    },
})
