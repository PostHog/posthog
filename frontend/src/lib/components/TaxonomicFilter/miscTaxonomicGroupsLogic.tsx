import { connect, kea, key, path, props, selectors } from 'kea'

import { propertyTaxonomicGroupProps } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    SimpleOption,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { isString } from 'lib/utils'
import { getEventDefinitionIcon, getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { getProductEventPropertyFilterOptions } from 'scenes/hog-functions/filters/HogFunctionFiltersInternal'
import { teamLogic } from 'scenes/teamLogic'

import { actionsModel } from '~/models/actionsModel'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { ActionType, PersonType } from '~/types'

import { HogFlowTaxonomicFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowTaxonomicFilters'

import type { miscTaxonomicGroupsLogicType } from './miscTaxonomicGroupsLogicType'

export const miscTaxonomicGroupsLogic = kea<miscTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'miscTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),

    selectors({
        propertyAllowList: [
            () => [(_, props) => props.propertyAllowList],
            (propertyAllowList) => propertyAllowList as TaxonomicFilterLogicProps['propertyAllowList'],
        ],
        activityWorkflowActionsTaxonomicGroups: [
            () => [],
            (): TaxonomicFilterGroup[] => [
                {
                    name: 'Activity log properties',
                    searchPlaceholder: 'activity log properties',
                    type: TaxonomicFilterGroupType.ActivityLogProperties,
                    options: getProductEventPropertyFilterOptions('activity-log').map((value) => ({
                        name: value,
                        value,
                        group: TaxonomicFilterGroupType.EventProperties,
                    })),
                    getIcon: getPropertyDefinitionIcon,
                    getPopoverHeader: () => 'Activity log properties',
                },
                {
                    name: 'Workflow variables',
                    searchPlaceholder: 'variable key',
                    type: TaxonomicFilterGroupType.WorkflowVariables,
                    categoryLabel: () => 'Workflow variables',
                    render: HogFlowTaxonomicFilters,
                    // Populated via optionsFromProp from the workflow scene so the All/Suggestions
                    // tab can aggregate workflow variables alongside other groups. The render
                    // override above still drives the dedicated tab UI.
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopoverHeader: () => 'Workflow variables',
                },
                {
                    name: 'Actions',
                    searchPlaceholder: 'actions',
                    type: TaxonomicFilterGroupType.Actions,
                    logic: actionsModel,
                    value: 'actionsSorted',
                    getName: (action: ActionType) => action.name || '',
                    getValue: (action: ActionType) => action.id,
                    getPopoverHeader: () => 'Action',
                    getIcon: getEventDefinitionIcon,
                },
            ],
        ],
        elementsMetadataTaxonomicGroups: [
            () => [],
            (): TaxonomicFilterGroup[] => [
                {
                    name: 'Autocapture elements',
                    searchPlaceholder: 'autocapture elements',
                    type: TaxonomicFilterGroupType.Elements,
                    options: ['tag_name', 'text', 'href', 'selector'].map((option) => ({
                        name: option,
                    })) as SimpleOption[],
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopoverHeader: () => 'Autocapture Element',
                },
                {
                    name: 'Metadata',
                    searchPlaceholder: 'metadata',
                    type: TaxonomicFilterGroupType.Metadata,
                    // populate options using `optionsFromProp` depending on context in which
                    // this taxonomic group type is used
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    ...propertyTaxonomicGroupProps(CORE_FILTER_DEFINITIONS_BY_GROUP.metadata),
                },
            ],
        ],
        wildcardsPersonsTaxonomicGroups: [
            (s) => [s.currentTeam],
            (currentTeam): TaxonomicFilterGroup[] => {
                const teamId = currentTeam?.id
                return [
                    {
                        name: 'Wildcards',
                        searchPlaceholder: 'wildcards',
                        type: TaxonomicFilterGroupType.Wildcards,
                        // Populated via optionsFromProp
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Wildcard`,
                    },
                    {
                        name: 'Persons',
                        searchPlaceholder: 'persons',
                        type: TaxonomicFilterGroupType.Persons,
                        endpoint: `api/environments/${teamId}/persons/`,
                        getName: (person: PersonType) => person.name || 'Anon user?',
                        getValue: (person: PersonType) => person.distinct_ids?.[0],
                        getPopoverHeader: () => `Person`,
                    },
                ]
            },
        ],
        sessionPropertiesTaxonomicGroups: [
            (s) => [s.currentTeam, s.propertyAllowList],
            (currentTeam, propertyAllowList): TaxonomicFilterGroup[] => {
                const teamId = currentTeam?.id
                return [
                    {
                        name: 'Session properties',
                        searchPlaceholder: 'sessions',
                        type: TaxonomicFilterGroupType.SessionProperties,
                        ...(propertyAllowList
                            ? {
                                  options: propertyAllowList[TaxonomicFilterGroupType.SessionProperties]
                                      ?.filter(isString)
                                      ?.map((property: string) => ({
                                          name: property,
                                          value: property,
                                      })),
                              }
                            : {
                                  endpoint: `api/environments/${teamId}/sessions/property_definitions`,
                              }),
                        getName: (option: any) => option.name,
                        getValue: (option) => option.name,
                        getPopoverHeader: () => 'Session',
                        getIcon: getPropertyDefinitionIcon,
                    },
                ]
            },
        ],
    }),
])
