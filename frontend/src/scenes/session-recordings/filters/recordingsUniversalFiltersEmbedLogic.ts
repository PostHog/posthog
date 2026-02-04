import { connect, kea, path, selectors } from 'kea'

import { PropertyDefinitionStorage, propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionState, PropertyDefinitionType, PropertyFilterType } from '~/types'

import type { recordingsUniversalFiltersEmbedLogicType } from './recordingsUniversalFiltersEmbedLogicType'

export type PersonOrEventPropertyFilterType = PropertyFilterType.Person | PropertyFilterType.Event

export interface PropertyCheckState {
    propertyState: PropertyDefinitionState | null
    propertyMissing: boolean
    propertyLoading: boolean
}

export const recordingsUniversalFiltersEmbedLogic = kea<recordingsUniversalFiltersEmbedLogicType>([
    path(() => ['scenes', 'session-recordings', 'filters', 'recordingsUniversalFiltersEmbedLogic']),
    connect(() => ({
        values: [propertyDefinitionsModel, ['propertyDefinitionStorage']],
    })),
    selectors(() => ({
        getPropertyCheckState: [
            (s) => [s.propertyDefinitionStorage],
            (propertyDefinitionStorage: PropertyDefinitionStorage) => {
                return (filterKey: string, propertyType: PersonOrEventPropertyFilterType): PropertyCheckState => {
                    const isPersonProperty = propertyType === PropertyFilterType.Person
                    const propertyKey = `${PropertyDefinitionType.Person}/${filterKey}`
                    const storedValue = isPersonProperty ? propertyDefinitionStorage[propertyKey] : null

                    // The stored value can be either a PropertyDefinition object or a PropertyDefinitionState
                    // If it's an object (PropertyDefinition), the property exists
                    // If it's a state value, we check which state it is
                    const propertyState =
                        storedValue && typeof storedValue === 'object' && storedValue !== null
                            ? null
                            : (storedValue as PropertyDefinitionState | null)

                    const propertyMissing = propertyState === PropertyDefinitionState.Missing
                    const propertyLoading =
                        propertyState === PropertyDefinitionState.Loading ||
                        propertyState === PropertyDefinitionState.Pending

                    return {
                        propertyState,
                        propertyMissing,
                        propertyLoading,
                    }
                }
            },
        ],
    })),
])
