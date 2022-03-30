import React from 'react'
import { kea } from 'kea'
import { TaxonomicFilterValue, ListStorage } from 'lib/components/TaxonomicFilter/types'
import { UniversalSearchGroup, UniversalSearchGroupType, UniversalSearchLogicProps } from './types'
import { searchListLogic } from 'lib/components/UniversalSearch/searchListLogic'
import {
    ActionType,
    CohortType,
    EventDefinition,
    FeatureFlagType,
    Group,
    InsightModel,
    PersonType,
    PropertyDefinition,
} from '~/types'
import { cohortsModel } from '~/models/cohortsModel'
import { actionsModel } from '~/models/actionsModel'
import { teamLogic } from 'scenes/teamLogic'
import { groupsModel } from '~/models/groupsModel'
import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { combineUrl } from 'kea-router'
import { ActionStack, CohortIcon } from 'lib/components/icons'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { getEventDefinitionIcon, getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'

import { universalSearchLogicType } from './universalSearchLogicType'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
const eventTaxonomicGroupProps: Pick<UniversalSearchGroup, 'getPopupHeader' | 'getIcon'> = {
    getPopupHeader: (eventDefinition: EventDefinition): string => {
        if (!!keyMapping.event[eventDefinition.name]) {
            return 'Verified Event'
        }
        return `${eventDefinition.verified ? 'Verified' : 'Unverified'} Event`
    },
    getIcon: getEventDefinitionIcon,
}

const propertyTaxonomicGroupProps = (
    verified: boolean = false
): Pick<UniversalSearchGroup, 'getPopupHeader' | 'getIcon'> => ({
    getPopupHeader: (propertyDefinition: PropertyDefinition): string => {
        if (verified || !!keyMapping.event[propertyDefinition.name]) {
            return 'Verified Property'
        }
        return 'Property'
    },
    getIcon: getPropertyDefinitionIcon,
})

export const universalSearchLogic = kea<universalSearchLogicType>({
    path: (key) => ['lib', 'components', 'UniversalSearch', 'universalSearchLogic', key],
    props: {} as UniversalSearchLogicProps,
    key: (props) => `${props.universalSearchLogicKey}`,
    connect: {
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            groupPropertiesModel,
            ['allGroupProperties'],
        ],
    },
    actions: () => ({
        moveUp: true,
        moveDown: true,
        selectSelected: (onComplete?: () => void) => ({ onComplete }),
        enableMouseInteractions: true,
        tabLeft: true,
        tabRight: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setActiveTab: (activeTab: UniversalSearchGroupType) => ({ activeTab }),
        selectItem: (group: UniversalSearchGroup, value: TaxonomicFilterValue | null, item: any) => ({
            group,
            value,
            item,
        }),
        infiniteListResultsReceived: (groupType: UniversalSearchGroupType, results: ListStorage) => ({
            groupType,
            results,
        }),
    }),

    reducers: ({ selectors }) => ({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        activeTab: [
            (state: any): UniversalSearchGroupType => {
                return selectors.groupType(state) || selectors.taxonomicGroupTypes(state)[0]
            },
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
        mouseInteractionsEnabled: [
            // This fixes a bug with keyboard up/down scrolling when the mouse is over the list.
            // Otherwise shifting list elements cause the "hover" action to be triggered randomly.
            true,
            {
                moveUp: () => false,
                moveDown: () => false,
                setActiveTab: () => true,
                enableMouseInteractions: () => true,
            },
        ],
    }),

    // NB, don't change to the async "selectors: (logic) => {}", as this causes a white screen when infiniteListLogic-s
    // connect to taxonomicFilterLogic to select their initial values. They won't be built yet and will be unknown.
    selectors: {
        universalSerchLogicKey: [
            () => [(_, props) => props.universalSerchLogicKey],
            (universalSerchLogicKey) => universalSerchLogicKey,
        ],
        eventNames: [() => [(_, props) => props.eventNames], (eventNames) => eventNames ?? []],
        taxonomicGroups: [
            (selectors) => [selectors.currentTeamId, selectors.groupAnalyticsTaxonomicGroups, selectors.eventNames],
            (teamId, groupAnalyticsTaxonomicGroups, eventNames): UniversalSearchGroup[] => [
                {
                    name: 'Events',
                    searchPlaceholder: 'events',
                    type: UniversalSearchGroupType.Events,
                    endpoint: `api/projects/${teamId}/event_definitions`,
                    getName: (eventDefinition: EventDefinition) => eventDefinition.name,
                    getValue: (eventDefinition: EventDefinition) => eventDefinition.name,
                    ...eventTaxonomicGroupProps,
                },
                {
                    name: 'Actions',
                    searchPlaceholder: 'actions',
                    type: UniversalSearchGroupType.Actions,
                    logic: actionsModel,
                    value: 'actions',
                    getName: (action: ActionType) => action.name || '',
                    getValue: (action: ActionType) => action.id,
                    getPopupHeader: () => 'Action',
                    getIcon: function _getIcon(): JSX.Element {
                        return <ActionStack className="taxonomy-icon taxonomy-icon-muted" />
                    },
                },
                {
                    name: 'Event properties',
                    searchPlaceholder: 'event properties',
                    type: UniversalSearchGroupType.EventProperties,
                    endpoint: combineUrl(
                        `api/projects/${teamId}/property_definitions`,
                        eventNames.length > 0 ? { event_names: eventNames } : {}
                    ).url,
                    scopedEndpoint:
                        eventNames.length > 0
                            ? combineUrl(`api/projects/${teamId}/property_definitions`, {
                                  event_names: eventNames,
                                  is_event_property: true,
                              }).url
                            : undefined,
                    expandLabel: ({ count, expandedCount }) =>
                        `Show ${pluralize(expandedCount - count, 'property', 'properties')} that ${pluralize(
                            eventNames.length,
                            'has',
                            'have',
                            false
                        )}n't been seen with ${pluralize(eventNames.length, 'this event', 'these events', false)}`,
                    getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    ...propertyTaxonomicGroupProps(),
                },
                {
                    name: 'Numerical event properties',
                    searchPlaceholder: 'numerical event properties',
                    type: UniversalSearchGroupType.NumericalEventProperties,
                    endpoint: combineUrl(`api/projects/${teamId}/property_definitions`, {
                        is_numerical: true,
                        event_names: eventNames,
                    }).url,
                    getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    ...propertyTaxonomicGroupProps(),
                },
                {
                    name: 'Persons',
                    searchPlaceholder: 'persons',
                    type: UniversalSearchGroupType.Persons,
                    endpoint: `api/projects/${teamId}/persons/`,
                    getName: (person: PersonType) => person.name || 'Anon user?',
                    getValue: (person: PersonType) => person.distinct_ids[0],
                    //TODO: Fix!
                    getPopupHeader: (person: PersonType) => `${person.is_static ? 'Static' : 'Dynamic'} Cohort`,
                },
                {
                    name: 'Insights',
                    searchPlaceholder: 'insights',
                    type: UniversalSearchGroupType.Insights,
                    endpoint: combineUrl(`api/projects/${teamId}/insights/`, {
                        saved: true,
                    }).url,
                    getName: (insight: InsightModel) => insight.name,
                    getValue: (insight: InsightModel) => insight.short_id,
                    //TODO: Fix!
                    getPopupHeader: (person: PersonType) => `${person.is_static ? 'Static' : 'Dynamic'} Cohort`,
                },
                {
                    name: 'Cohorts',
                    searchPlaceholder: 'cohorts',
                    type: UniversalSearchGroupType.Cohorts,
                    logic: cohortsModel,
                    value: 'cohorts',
                    getName: (cohort: CohortType) => cohort.name || `Cohort ${cohort.id}`,
                    getValue: (cohort: CohortType) => cohort.id,
                    getPopupHeader: (cohort: CohortType) => `${cohort.is_static ? 'Static' : 'Dynamic'} Cohort`,
                    getIcon: function _getIcon(): JSX.Element {
                        return <CohortIcon className="taxonomy-icon taxonomy-icon-muted" />
                    },
                },
                {
                    name: 'Feature Flags',
                    searchPlaceholder: 'feature flags',
                    type: UniversalSearchGroupType.FeatureFlags,
                    logic: featureFlagsLogic,
                    value: 'featureFlags',
                    getName: (featureFlag: FeatureFlagType) => featureFlag.name || featureFlag.key,
                    getValue: (featureFlag: FeatureFlagType) => featureFlag.id || '',
                    getPopupHeader: () => 'Feature Flag',
                    // getIcon: function _getIcon(): JSX.Element {
                    //     return <ActionStack className="taxonomy-icon taxonomy-icon-muted" />
                    // },
                },
                ...groupAnalyticsTaxonomicGroups,
            ],
        ],
        activeTaxonomicGroup: [
            (s) => [s.activeTab, s.taxonomicGroups],
            (activeTab, taxonomicGroups) => taxonomicGroups.find((g) => g.type === activeTab),
        ],
        taxonomicGroupTypes: [
            (selectors) => [(_, props) => props.taxonomicGroupTypes, selectors.taxonomicGroups],
            (groupTypes, taxonomicGroups): UniversalSearchGroupType[] =>
                groupTypes || taxonomicGroups.map((g) => g.type),
        ],
        groupAnalyticsTaxonomicGroups: [
            (selectors) => [selectors.groupTypes, selectors.currentTeamId, selectors.aggregationLabel],
            (groupTypes, teamId, aggregationLabel): UniversalSearchGroup[] =>
                groupTypes.map((type) => ({
                    name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).plural)}`,
                    searchPlaceholder: `${aggregationLabel(type.group_type_index).plural}`,
                    type: `${UniversalSearchGroupType.GroupsPrefix}_${type.group_type_index}` as unknown as UniversalSearchGroupType,
                    endpoint: combineUrl(`api/projects/${teamId}/groups/`, {
                        group_type_index: type.group_type_index,
                    }).url,
                    searchAlias: 'group_key',
                    getName: (group: Group) => groupDisplayId(group.group_key, group.group_properties),
                    getValue: (group: Group) => group.group_key,
                    getPopupHeader: () => `Property`,
                    getIcon: getPropertyDefinitionIcon,
                    groupTypeIndex: type.group_type_index,
                })),
        ],
        infiniteListLogics: [
            (s) => [s.taxonomicGroupTypes, (_, props) => props],
            (taxonomicGroupTypes, props): Record<string, ReturnType<typeof searchListLogic.build>> =>
                Object.fromEntries(
                    taxonomicGroupTypes.map((groupType) => [
                        groupType,
                        searchListLogic.build({
                            ...props,
                            listGroupType: groupType,
                        }),
                    ])
                ),
        ],
        infiniteListCounts: [
            (s) => [
                (state, props) =>
                    Object.fromEntries(
                        Object.entries(s.infiniteListLogics(state, props)).map(([groupType, logic]) => [
                            groupType,
                            logic.isMounted() ? logic.selectors.totalListCount(state, logic.props) : 0,
                        ])
                    ),
            ],
            (infiniteListCounts) => infiniteListCounts,
        ],
        value: [() => [(_, props) => props.value], (value) => value],
        groupType: [() => [(_, props) => props.groupType], (groupType) => groupType],
        currentTabIndex: [
            (s) => [s.taxonomicGroupTypes, s.activeTab],
            (groupTypes, activeTab) => Math.max(groupTypes.indexOf(activeTab || ''), 0),
        ],
        searchPlaceholder: [
            (s) => [s.taxonomicGroups, s.taxonomicGroupTypes],
            (allTaxonomicGroups, searchGroupTypes) => {
                if (searchGroupTypes.length > 1) {
                    searchGroupTypes = searchGroupTypes.filter(
                        (type) => !type.startsWith(UniversalSearchGroupType.GroupsPrefix)
                    )
                }
                const names = searchGroupTypes.map((type) => {
                    const taxonomicGroup = allTaxonomicGroups.find(
                        (tGroup) => tGroup.type == type
                    ) as UniversalSearchGroup
                    return taxonomicGroup.searchPlaceholder
                })
                return names
                    .map(
                        (name, index) =>
                            `${index !== 0 ? (index === searchGroupTypes.length - 1 ? ' or ' : ', ') : ''}${name}`
                    )
                    .join('')
            },
        ],
    },
    listeners: ({ actions, values, props }) => ({
        selectItem: ({ group, value, item }) => {
            if (item && value) {
                props.onChange?.(group, value, item)
            }
            actions.setSearchQuery('')
        },

        moveUp: async (_, breakpoint) => {
            if (values.activeTab) {
                searchListLogic({
                    ...props,
                    listGroupType: values.activeTab,
                }).actions.moveUp()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        moveDown: async (_, breakpoint) => {
            if (values.activeTab) {
                searchListLogic({
                    ...props,
                    listGroupType: values.activeTab,
                }).actions.moveDown()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        selectSelected: async (_, breakpoint) => {
            if (values.activeTab) {
                searchListLogic({
                    ...props,
                    listGroupType: values.activeTab,
                }).actions.selectSelected()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        tabLeft: () => {
            const { currentTabIndex, taxonomicGroupTypes, infiniteListCounts } = values
            for (let i = 1; i < taxonomicGroupTypes.length; i++) {
                const newIndex = (currentTabIndex - i + taxonomicGroupTypes.length) % taxonomicGroupTypes.length
                if (infiniteListCounts[taxonomicGroupTypes[newIndex]] > 0) {
                    actions.setActiveTab(taxonomicGroupTypes[newIndex])
                    return
                }
            }
        },

        tabRight: () => {
            const { currentTabIndex, taxonomicGroupTypes, infiniteListCounts } = values
            for (let i = 1; i < taxonomicGroupTypes.length; i++) {
                const newIndex = (currentTabIndex + i) % taxonomicGroupTypes.length
                if (infiniteListCounts[taxonomicGroupTypes[newIndex]] > 0) {
                    actions.setActiveTab(taxonomicGroupTypes[newIndex])
                    return
                }
            }
        },

        setSearchQuery: () => {
            const { activeTaxonomicGroup, infiniteListCounts } = values

            // Taxonomic group with a local data source, zero results after searching.
            // Open the next tab.
            if (
                activeTaxonomicGroup &&
                !activeTaxonomicGroup.endpoint &&
                infiniteListCounts[activeTaxonomicGroup.type] === 0
            ) {
                actions.tabRight()
            }
        },

        infiniteListResultsReceived: ({ groupType, results }) => {
            // Open the next tab if no results on an active tab.
            if (groupType === values.activeTab && !results.count && !results.expandedCount) {
                actions.tabRight()
            }
        },
    }),
})
