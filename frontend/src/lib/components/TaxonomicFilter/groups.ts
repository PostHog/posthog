import { personPropertiesModel } from '~/models/personPropertiesModel'
import { ActionType, CohortType, EventDefinition, PersonProperty, PropertyDefinition } from '~/types'
import { cohortsModel } from '~/models/cohortsModel'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { actionsModel } from '~/models/actionsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'

export type SimpleOption = {
    name: string
}

export const groups: TaxonomicFilterGroup[] = [
    {
        name: 'Events',
        type: TaxonomicFilterGroupType.Events,
        endpoint: 'api/projects/@current/event_definitions',
        getName: (eventDefinition: EventDefinition): string => eventDefinition.name,
        getValue: (eventDefinition: EventDefinition): TaxonomicFilterValue => eventDefinition.name,
    },
    {
        name: 'Actions',
        type: TaxonomicFilterGroupType.Actions,
        logic: actionsModel,
        value: 'actions',
        getName: (action: ActionType): string => action.name,
        getValue: (action: ActionType): TaxonomicFilterValue => action.id,
    },
    {
        name: 'Elements',
        type: TaxonomicFilterGroupType.Elements,
        options: ['tag_name', 'text', 'href', 'selector'].map((option) => ({
            name: option,
        })) as SimpleOption[],
        getName: (option: SimpleOption): string => option.name,
        getValue: (option: SimpleOption): TaxonomicFilterValue => option.name,
    },
    {
        name: 'Event properties',
        type: TaxonomicFilterGroupType.EventProperties,
        endpoint: 'api/projects/@current/property_definitions',
        getName: (propertyDefinition: PropertyDefinition): string => propertyDefinition.name,
        getValue: (propertyDefinition: PropertyDefinition): TaxonomicFilterValue => propertyDefinition.name,
    },
    {
        name: 'Person properties',
        type: TaxonomicFilterGroupType.PersonProperties,
        logic: personPropertiesModel,
        value: 'personProperties',
        getName: (personProperty: PersonProperty): string => personProperty.name,
        getValue: (personProperty: PersonProperty): TaxonomicFilterValue => personProperty.name,
    },
    {
        name: 'Cohorts',
        type: TaxonomicFilterGroupType.Cohorts,
        logic: cohortsModel,
        value: 'cohorts',
        getName: (cohort: CohortType): string => cohort.name || `Cohort ${cohort.id}`,
        getValue: (cohort: CohortType): TaxonomicFilterValue => cohort.id,
    },
    {
        name: 'Cohorts',
        type: TaxonomicFilterGroupType.CohortsWithAllUsers,
        logic: cohortsModel,
        value: 'cohortsWithAllUsers',
        getName: (cohort: CohortType): string => cohort.name || `Cohort ${cohort.id}`,
        getValue: (cohort: CohortType): TaxonomicFilterValue => cohort.id,
    },
    {
        name: 'Pageview Urls',
        type: TaxonomicFilterGroupType.PageviewUrls,
        endpoint: 'api/event/values/?key=$current_url',
        searchAlias: 'value',
        getName: ({ name }: { name: string }): string => name,
        getValue: ({ name }: { name: string }): TaxonomicFilterValue => name,
    },
    {
        name: 'Screens',
        type: TaxonomicFilterGroupType.Screens,
        endpoint: 'api/event/values/?key=$screen_name',
        searchAlias: 'value',
        getName: ({ name }: { name: string }): string => name,
        getValue: ({ name }: { name: string }): TaxonomicFilterValue => name,
    },
    {
        name: 'Custom Events',
        type: TaxonomicFilterGroupType.CustomEvents,
        logic: eventDefinitionsModel,
        value: 'customEvents',
        getName: (eventDefinition: EventDefinition): string => eventDefinition.name,
        getValue: (eventDefinition: EventDefinition): TaxonomicFilterValue => eventDefinition.name,
    },
    {
        name: 'Wildcards',
        type: TaxonomicFilterGroupType.Wildcards,
        // Populated via optionsFromProp
        getName: (option: SimpleOption): string => option.name,
        getValue: (option: SimpleOption): TaxonomicFilterValue => option.name,
    },
]
