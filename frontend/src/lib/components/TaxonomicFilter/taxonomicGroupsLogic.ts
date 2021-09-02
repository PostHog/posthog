import { kea } from 'kea'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { ActionType, CohortType, EventDefinition, GroupType, PersonProperty, PropertyDefinition } from '~/types'
import { cohortsModel } from '~/models/cohortsModel'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { actionsModel } from '~/models/actionsModel'
import { taxonomicGroupsLogicType } from './taxonomicGroupsLogicType'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { groupsLogic } from 'scenes/groups/groupsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { capitalizeFirstLetter } from 'lib/utils'

type SimpleOption = {
    name: string
}

export const taxonomicGroupsLogic = kea<taxonomicGroupsLogicType>({
    selectors: {
        groups: [
            (s) => [s.groupTypes],
            (groupTypes: GroupType[]): TaxonomicFilterGroup[] => [
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
                // @ts-ignore
                ...groupTypes.map((groupType) => {
                    const logic = groupPropertiesModel({ typeId: groupType.type_id })
                    logic.mount()
                    return {
                        name: capitalizeFirstLetter(groupType.type_key),
                        type: `group::${groupType.type_id}`,
                        logic: logic,
                        // value: `$group_${groupType.type_id}`,
                        value: 'groupProperties',
                        groupAnalytics: true,
                        getName: (personProperty: PersonProperty): string => personProperty.name,
                        getValue: (personProperty: PersonProperty): TaxonomicFilterValue => personProperty.name,
                    }
                }),
            ],
        ],
        groupTypes: [
            () => [featureFlagLogic.selectors.featureFlags, groupsLogic.selectors.groupTypes],
            (featureFlags: FeatureFlagsSet, groupTypes: GroupType[]): GroupType[] =>
                featureFlags[FEATURE_FLAGS.GROUPS] ? groupTypes : [],
        ],
    },
})
