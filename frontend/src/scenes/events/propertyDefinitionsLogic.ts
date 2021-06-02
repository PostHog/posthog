import { kea } from 'kea'
import { insightDataCachingLogic } from 'lib/logic/insightDataCachingLogic'
import { PropertyDefinition, SelectOption } from '~/types'
import { propertyDefinitionsLogicType } from './propertyDefinitionsLogicType'

interface PropertySelectOption extends SelectOption {
    is_numerical?: boolean
}

interface PropertyDefinitionStorage {
    count: number
    next: null | string
    results: PropertyDefinition[]
}

export const propertyDefinitionsLogic = kea<
    propertyDefinitionsLogicType<PropertyDefinitionStorage, PropertyDefinition, PropertySelectOption>
>({
    connect: {
        actions: [insightDataCachingLogic, ['maybeLoadData']],
        values: [insightDataCachingLogic, ['cachedData', 'cacheLoading']],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.maybeLoadData({
                key: 'propertyDefinitions',
                endpoint: 'api/projects/@current/property_definitions/?limit=5000',
                paginated: true,
            })
        },
    }),
    selectors: {
        propertyStorage: [
            (s) => [s.cachedData],
            (cachedData): PropertyDefinitionStorage => {
                if (cachedData['propertyDefinitions']) {
                    return cachedData['propertyDefinitions']
                }
                return { results: [], next: null, count: 0 }
            },
        ],
        loaded: [
            // Whether *all* the event definitions are fully loaded
            (s) => [s.propertyStorage, s.cacheLoading],
            (propertyStorage, cacheLoading): boolean => !cacheLoading['propertyDefinitions'] && !propertyStorage.next,
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
