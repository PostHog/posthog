import React from 'react'
import { BuiltLogic, kea } from 'kea'
import type { taxonomicFilterLogicType } from './taxonomicFilterLogicType'
import {
    SimpleOption,
    TaxonomicFilterGroupType,
    TaxonomicFilterGroup,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
    ListStorage,
} from 'lib/components/TaxonomicFilter/types'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import {
    ActionType,
    CohortType,
    DashboardType,
    EventDefinition,
    Experiment,
    FeatureFlagType,
    Group,
    InsightModel,
    PersonProperty,
    PersonType,
    PluginType,
    PropertyDefinition,
} from '~/types'
import { cohortsModel } from '~/models/cohortsModel'
import { actionsModel } from '~/models/actionsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { teamLogic } from 'scenes/teamLogic'
import { groupsModel } from '~/models/groupsModel'
import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { capitalizeFirstLetter, pluralize, toParams } from 'lib/utils'
import { combineUrl } from 'kea-router'
import { ActionStack, CohortIcon } from 'lib/components/icons'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { getEventDefinitionIcon, getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'

export const eventTaxonomicGroupProps: Pick<TaxonomicFilterGroup, 'getPopupHeader' | 'getIcon'> = {
    getPopupHeader: (eventDefinition: EventDefinition): string => {
        if (!!keyMapping.event[eventDefinition.name]) {
            return 'Verified Event'
        }
        return `${eventDefinition.verified ? 'Verified' : 'Unverified'} Event`
    },
    getIcon: getEventDefinitionIcon,
}

export const propertyTaxonomicGroupProps = (
    verified: boolean = false
): Pick<TaxonomicFilterGroup, 'getPopupHeader' | 'getIcon'> => ({
    getPopupHeader: (propertyDefinition: PropertyDefinition): string => {
        if (verified || !!keyMapping.event[propertyDefinition.name]) {
            return 'Verified Property'
        }
        return 'Property'
    },
    getIcon: getPropertyDefinitionIcon,
})

export const taxonomicFilterLogic = kea<taxonomicFilterLogicType>({
    path: ['lib', 'components', 'TaxonomicFilter', 'taxonomicFilterLogic'],
    props: {} as TaxonomicFilterLogicProps,
    key: (props) => `${props.taxonomicFilterLogicKey}`,
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
        setActiveTab: (activeTab: TaxonomicFilterGroupType) => ({ activeTab }),
        selectItem: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue | null, item: any) => ({
            group,
            value,
            item,
        }),
        infiniteListResultsReceived: (groupType: TaxonomicFilterGroupType, results: ListStorage) => ({
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
            (state: any): TaxonomicFilterGroupType => {
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
        taxonomicFilterLogicKey: [
            () => [(_, props) => props.taxonomicFilterLogicKey],
            (taxonomicFilterLogicKey) => taxonomicFilterLogicKey,
        ],
        eventNames: [() => [(_, props) => props.eventNames], (eventNames) => eventNames ?? []],
        taxonomicGroups: [
            (selectors) => [
                selectors.currentTeamId,
                selectors.groupAnalyticsTaxonomicGroups,
                selectors.groupAnalyticsTaxonomicGroupNames,
                selectors.eventNames,
            ],
            (
                teamId,
                groupAnalyticsTaxonomicGroups,
                groupAnalyticsTaxonomicGroupNames,
                eventNames
            ): TaxonomicFilterGroup[] => [
                {
                    name: 'Events',
                    searchPlaceholder: 'events',
                    type: TaxonomicFilterGroupType.Events,
                    endpoint: `api/projects/${teamId}/event_definitions`,
                    getName: (eventDefinition: EventDefinition) => eventDefinition.name,
                    getValue: (eventDefinition: EventDefinition) => eventDefinition.name,
                    ...eventTaxonomicGroupProps,
                },
                {
                    name: 'Actions',
                    searchPlaceholder: 'actions',
                    type: TaxonomicFilterGroupType.Actions,
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
                    name: 'Autocapture elements',
                    searchPlaceholder: 'autocapture elements',
                    type: TaxonomicFilterGroupType.Elements,
                    options: ['tag_name', 'text', 'href', 'selector'].map((option) => ({
                        name: option,
                    })) as SimpleOption[],
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopupHeader: () => 'Autocapture Element',
                },
                {
                    name: 'Event properties',
                    searchPlaceholder: 'event properties',
                    type: TaxonomicFilterGroupType.EventProperties,
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
                    type: TaxonomicFilterGroupType.NumericalEventProperties,
                    endpoint: combineUrl(`api/projects/${teamId}/property_definitions`, {
                        is_numerical: true,
                        event_names: eventNames,
                    }).url,
                    getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                    ...propertyTaxonomicGroupProps(),
                },
                {
                    name: 'Person properties',
                    searchPlaceholder: 'person properties',
                    type: TaxonomicFilterGroupType.PersonProperties,
                    logic: personPropertiesModel,
                    value: 'personProperties',
                    getName: (personProperty: PersonProperty) => personProperty.name,
                    getValue: (personProperty: PersonProperty) => personProperty.name,
                    ...propertyTaxonomicGroupProps(true),
                },
                {
                    name: 'Cohorts',
                    searchPlaceholder: 'cohorts',
                    type: TaxonomicFilterGroupType.Cohorts,
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
                    name: 'Cohorts',
                    searchPlaceholder: 'cohorts',
                    type: TaxonomicFilterGroupType.CohortsWithAllUsers,
                    logic: cohortsModel,
                    value: 'cohortsWithAllUsers',
                    getName: (cohort: CohortType) => cohort.name || `Cohort ${cohort.id}`,
                    getValue: (cohort: CohortType) => cohort.id,
                    getPopupHeader: () => `All Users`,
                    getIcon: function _getIcon(): JSX.Element {
                        return <CohortIcon className="taxonomy-icon taxonomy-icon-muted" />
                    },
                },
                {
                    name: 'Pageview URLs',
                    searchPlaceholder: 'pageview URLs',
                    type: TaxonomicFilterGroupType.PageviewUrls,
                    endpoint: `api/projects/${teamId}/events/values/?key=$current_url`,
                    searchAlias: 'value',
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopupHeader: () => `Pageview URL`,
                },
                {
                    name: 'Screens',
                    searchPlaceholder: 'screens',
                    type: TaxonomicFilterGroupType.Screens,
                    endpoint: `api/projects/${teamId}/events/values/?key=$screen_name`,
                    searchAlias: 'value',
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopupHeader: () => `Screen`,
                },
                {
                    name: 'Custom Events',
                    searchPlaceholder: 'custom events',
                    type: TaxonomicFilterGroupType.CustomEvents,
                    logic: eventDefinitionsModel,
                    value: 'customEvents',
                    getName: (eventDefinition: EventDefinition) => eventDefinition.name,
                    getValue: (eventDefinition: EventDefinition) => eventDefinition.name,
                    ...eventTaxonomicGroupProps,
                },
                {
                    name: 'Wildcards',
                    searchPlaceholder: 'wildcards',
                    type: TaxonomicFilterGroupType.Wildcards,
                    // Populated via optionsFromProp
                    getName: (option: SimpleOption) => option.name,
                    getValue: (option: SimpleOption) => option.name,
                    getPopupHeader: () => `Wildcard`,
                },
                {
                    name: 'Persons',
                    searchPlaceholder: 'persons',
                    type: TaxonomicFilterGroupType.Persons,
                    endpoint: `api/projects/${teamId}/persons/`,
                    getName: (person: PersonType) => person.name || 'Anon user?',
                    getValue: (person: PersonType) => person.distinct_ids[0],
                    getPopupHeader: () => `Person`,
                },
                {
                    name: 'Insights',
                    searchPlaceholder: 'insights',
                    type: TaxonomicFilterGroupType.Insights,
                    endpoint: combineUrl(`api/projects/${teamId}/insights/`, {
                        saved: true,
                    }).url,
                    getName: (insight: InsightModel) => insight.name,
                    getValue: (insight: InsightModel) => insight.short_id,
                    getPopupHeader: () => `Insights`,
                },
                {
                    name: 'Feature Flags',
                    searchPlaceholder: 'feature flags',
                    type: TaxonomicFilterGroupType.FeatureFlags,
                    logic: featureFlagsLogic,
                    value: 'featureFlags',
                    getName: (featureFlag: FeatureFlagType) => featureFlag.key || featureFlag.name,
                    getValue: (featureFlag: FeatureFlagType) => featureFlag.id || '',
                    getPopupHeader: () => `Feature Flags`,
                },
                {
                    name: 'Experiments',
                    searchPlaceholder: 'experiments',
                    type: TaxonomicFilterGroupType.Experiments,
                    logic: experimentsLogic,
                    value: 'experiments',
                    getName: (experiment: Experiment) => experiment.name,
                    getValue: (experiment: Experiment) => experiment.id,
                    getPopupHeader: () => `Experiments`,
                },
                {
                    name: 'Plugins',
                    searchPlaceholder: 'plugins',
                    type: TaxonomicFilterGroupType.Plugins,
                    logic: pluginsLogic,
                    value: 'allPossiblePlugins',
                    getName: (plugin: Pick<PluginType, 'name' | 'url'>) => plugin.name,
                    getValue: (plugin: Pick<PluginType, 'name' | 'url'>) => plugin.name,
                    getPopupHeader: () => `Plugins`,
                },
                {
                    name: 'Dashboards',
                    searchPlaceholder: 'dashboards',
                    type: TaxonomicFilterGroupType.Dashboards,
                    logic: dashboardsModel,
                    value: 'nameSortedDashboards',
                    getName: (dashboard: DashboardType) => dashboard.name,
                    getValue: (dashboard: DashboardType) => dashboard.id,
                    getPopupHeader: () => `Dashboards`,
                },
                ...groupAnalyticsTaxonomicGroups,
                ...groupAnalyticsTaxonomicGroupNames,
            ],
        ],
        activeTaxonomicGroup: [
            (s) => [s.activeTab, s.taxonomicGroups],
            (activeTab, taxonomicGroups) => taxonomicGroups.find((g) => g.type === activeTab),
        ],
        taxonomicGroupTypes: [
            (selectors) => [(_, props) => props.taxonomicGroupTypes, selectors.taxonomicGroups],
            (groupTypes, taxonomicGroups): TaxonomicFilterGroupType[] =>
                groupTypes || taxonomicGroups.map((g) => g.type),
        ],
        groupAnalyticsTaxonomicGroupNames: [
            (selectors) => [selectors.groupTypes, selectors.currentTeamId, selectors.aggregationLabel],
            (groupTypes, teamId, aggregationLabel): TaxonomicFilterGroup[] =>
                groupTypes.map((type) => ({
                    name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).plural)}`,
                    searchPlaceholder: `${aggregationLabel(type.group_type_index).plural}`,
                    type: `${TaxonomicFilterGroupType.GroupNamesPrefix}_${type.group_type_index}` as unknown as TaxonomicFilterGroupType,
                    endpoint: combineUrl(`api/projects/${teamId}/groups/`, {
                        group_type_index: type.group_type_index,
                    }).url,
                    searchAlias: 'group_key',
                    getPopupHeader: () => `Group Names`,
                    getName: (group: Group) => groupDisplayId(group.group_key, group.group_properties),
                    getValue: (group: Group) => group.group_key,
                    groupTypeIndex: type.group_type_index,
                })),
        ],
        groupAnalyticsTaxonomicGroups: [
            (selectors) => [selectors.groupTypes, selectors.currentTeamId, selectors.aggregationLabel],
            (groupTypes, teamId, aggregationLabel): TaxonomicFilterGroup[] =>
                groupTypes.map((type) => ({
                    name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).singular)} properties`,
                    searchPlaceholder: `${aggregationLabel(type.group_type_index).singular} properties`,
                    type: `${TaxonomicFilterGroupType.GroupsPrefix}_${type.group_type_index}` as unknown as TaxonomicFilterGroupType,
                    logic: groupPropertiesModel,
                    value: `groupProperties_${type.group_type_index}`,
                    valuesEndpoint: (key) =>
                        `api/projects/${teamId}/groups/property_values/?${toParams({
                            key,
                            group_type_index: type.group_type_index,
                        })}`,
                    getName: () => capitalizeFirstLetter(aggregationLabel(type.group_type_index).singular),
                    getValue: (group) => group.name,
                    getPopupHeader: () => `Property`,
                    getIcon: getPropertyDefinitionIcon,
                    groupTypeIndex: type.group_type_index,
                })),
        ],
        infiniteListLogics: [
            (s) => [s.taxonomicGroupTypes, (_, props) => props],
            (taxonomicGroupTypes, props): Record<string, BuiltLogic<infiniteListLogicType>> =>
                Object.fromEntries(
                    taxonomicGroupTypes.map((groupType) => [
                        groupType,
                        infiniteListLogic.build({
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
                        (type) =>
                            !type.startsWith(TaxonomicFilterGroupType.GroupsPrefix) &&
                            !type.startsWith(TaxonomicFilterGroupType.GroupNamesPrefix)
                    )
                }
                const names = searchGroupTypes.map((type) => {
                    const taxonomicGroup = allTaxonomicGroups.find(
                        (tGroup) => tGroup.type == type
                    ) as TaxonomicFilterGroup
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
                infiniteListLogic({
                    ...props,
                    listGroupType: values.activeTab,
                }).actions.moveUp()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        moveDown: async (_, breakpoint) => {
            if (values.activeTab) {
                infiniteListLogic({
                    ...props,
                    listGroupType: values.activeTab,
                }).actions.moveDown()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        selectSelected: async (_, breakpoint) => {
            if (values.activeTab) {
                infiniteListLogic({
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
