import { kea } from 'kea'
import api from 'lib/api'
import { PropertyDefinition, SelectOption } from '~/types'
import { propertyDefinitionsLogicType } from './propertyDefinitionsLogicType'

interface PropertyDefinitionStorage {
    count: number
    next: null | string
    results: PropertyDefinition[]
}

export const propertyDefinitionsLogic = kea<
    propertyDefinitionsLogicType<PropertyDefinitionStorage, PropertyDefinition, SelectOption>
>({
    reducers: {
        propertyStorage: [
            { results: [], next: null, count: 0 } as PropertyDefinitionStorage,
            {
                loadPropertyDefinitionsSuccess: (state, { propertyStorage }) => {
                    return {
                        count: propertyStorage.count,
                        results: [...state.results, ...propertyStorage.results],
                        next: propertyStorage.next,
                    }
                },
            },
        ],
    },
    loaders: ({ values }) => ({
        propertyStorage: [
            { results: [], next: null, count: 0 } as PropertyDefinitionStorage,
            {
                loadPropertyDefinitions: async (initial?: boolean) => {
                    const url = initial ? 'api/projects/@current/property_definitions/' : values.propertyStorage.next
                    if (!url) {
                        throw new Error('Incorrect call to propertyDefinitionsLogic.loadPropertyDefinitions')
                    }
                    return await api.get(url)
                },
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
            (propertyStorage: PropertyDefinitionStorage, propertyStorageLoading: boolean): boolean =>
                !propertyStorageLoading && !propertyStorage.next,
        ],
        propertyDefinitions: [
            (s) => [s.propertyStorage],
            (propertyStorage: PropertyDefinitionStorage): PropertyDefinition[] => propertyStorage.results || [],
        ],
        transformedPropertyDefinitions: [
            // Transformed propertyDefinitions to use in `Select` components
            (s) => [s.propertyDefinitions],
            (propertyDefinitions: PropertyDefinition[]): SelectOption[] =>
                propertyDefinitions.map((property) => ({
                    value: property.id,
                    label: property.name,
                })),
        ],
        propertyNames: [
            // TODO: This can be improved for performance by enabling downstream components to use `propertyDefinitions` directly and getting rid of this selector.
            (s) => [s.propertyDefinitions],
            (propertyDefinitions: PropertyDefinition[]): string[] =>
                propertyDefinitions.map((definition) => definition.name),
        ],
        numericalPropertyNames: [
            // TODO: This can be improved for performance by enabling downstream components to use `propertyDefinitions` directly and getting rid of this selector.
            (s) => [s.propertyDefinitions],
            (propertyDefinitions: PropertyDefinition[]): string[] =>
                propertyDefinitions
                    .filter((definition) => definition.is_numerical)
                    .map((definition) => definition.name),
        ],
    },
})
