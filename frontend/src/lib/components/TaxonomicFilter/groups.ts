import { personPropertiesModel } from '~/models/personPropertiesModel'
import {
    ActionType,
    CohortType,
    EventDefinition,
    PersonProperty,
    PropertyDefinition,
    PropertyFilterValue,
} from '~/types'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { actionsModel } from '~/models/actionsModel'

type SimpleOption = {
    name: string
}

export const groups: TaxonomicFilterGroup[] = [
    {
        name: 'Events',
        type: TaxonomicFilterGroupType.Events,
        endpoint: 'api/projects/@current/event_definitions',
        getName: (eventDefinition: EventDefinition): string => eventDefinition.name,
        getValue: (eventDefinition: EventDefinition): PropertyFilterValue => eventDefinition.name,
    },
    {
        name: 'Actions',
        type: TaxonomicFilterGroupType.Actions,
        logic: actionsModel,
        value: 'actions',
        getName: (action: ActionType): string => action.name,
        getValue: (action: ActionType): PropertyFilterValue => action.id,
    },
    {
        name: 'Elements',
        type: TaxonomicFilterGroupType.Elements,
        options: ['tag_name', 'text', 'href', 'selector'].map((option) => ({
            name: option,
        })) as SimpleOption[],
        getName: (option: SimpleOption): string => option.name,
        getValue: (option: SimpleOption): PropertyFilterValue => option.name,
    },
    {
        name: 'Event properties',
        type: TaxonomicFilterGroupType.EventProperties,
        endpoint: 'api/projects/@current/property_definitions',
        getName: (propertyDefinition: PropertyDefinition): string => propertyDefinition.name,
        getValue: (propertyDefinition: PropertyDefinition): PropertyFilterValue => propertyDefinition.name,
    },
    {
        name: 'Person properties',
        type: TaxonomicFilterGroupType.PersonProperties,
        logic: personPropertiesModel,
        value: 'personProperties',
        getName: (personProperty: PersonProperty): string => personProperty.name,
        getValue: (personProperty: PersonProperty): PropertyFilterValue => personProperty.name,
    },
    {
        name: 'Cohorts',
        type: TaxonomicFilterGroupType.Cohorts,
        logic: cohortsModel,
        value: 'cohorts',
        getName: (cohort: CohortType): string => cohort.name || `Cohort #${cohort.id}`,
        getValue: (cohort: CohortType): PropertyFilterValue => cohort.id,
    },
]
