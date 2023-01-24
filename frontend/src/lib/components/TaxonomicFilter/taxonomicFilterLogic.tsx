import { BuiltLogic, kea } from 'kea'
import type { taxonomicFilterLogicType } from './taxonomicFilterLogicType'
import {
    ListStorage,
    SimpleOption,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import {
    ActionType,
    CohortType,
    EventDefinitionType,
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
import { teamLogic } from 'scenes/teamLogic'
import { groupsModel } from '~/models/groupsModel'
import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { capitalizeFirstLetter, pluralize, toParams } from 'lib/utils'
import { combineUrl } from 'kea-router'
import { IconCohort } from 'lib/components/icons'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { getEventDefinitionIcon, getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { FEATURE_FLAGS } from 'lib/constants'
import { InlineHogQLEditor } from '~/queries/QueryEditor/InlineHogQLEditor'

export const eventTaxonomicGroupProps: Pick<TaxonomicFilterGroup, 'getPopupHeader' | 'getIcon'> = {
    getPopupHeader: (eventDefinition: EventDefinition): string => {
        if (!!keyMapping.event[eventDefinition.name]) {
            return 'PostHog event'
        }
        return `${eventDefinition.verified ? 'Verified' : 'Unverified'} event`
    },
    getIcon: getEventDefinitionIcon,
}

export const propertyTaxonomicGroupProps = (
    verified: boolean = false
): Pick<TaxonomicFilterGroup, 'getPopupHeader' | 'getIcon'> => ({
    getPopupHeader: (propertyDefinition: PropertyDefinition): string => {
        if (verified || !!keyMapping.event[propertyDefinition.name]) {
            return 'PostHog property'
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
            featureFlagLogic,
            ['featureFlags'],
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
        excludedProperties: [
            () => [(_, props) => props.excludedProperties],
            (excludedProperties) => excludedProperties ?? {},
        ],
        taxonomicGroups: [
            (s) => [
                s.currentTeamId,
                s.groupAnalyticsTaxonomicGroups,
                s.groupAnalyticsTaxonomicGroupNames,
                s.eventNames,
                s.excludedProperties,
                s.featureFlags,
            ],
            (
                teamId,
                groupAnalyticsTaxonomicGroups,
                groupAnalyticsTaxonomicGroupNames,
                eventNames,
                excludedProperties,
                featureFlags
            ): TaxonomicFilterGroup[] => {
                const hogQl: TaxonomicFilterGroup = {
                    name: 'HogQL',
                    searchPlaceholder: 'HogQL',
                    type: TaxonomicFilterGroupType.HogQLExpression,
                    render: InlineHogQLEditor,
                    getPopupHeader: () => 'HogQL',
                }
                return [
                    {
                        name: 'Events',
                        searchPlaceholder: 'events',
                        type: TaxonomicFilterGroupType.Events,
                        endpoint: combineUrl(`api/projects/${teamId}/event_definitions`, {
                            event_type: EventDefinitionType.Event,
                        }).url,
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
                        getIcon: getEventDefinitionIcon,
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
                        endpoint: combineUrl(`api/projects/${teamId}/property_definitions`, {
                            is_feature_flag: false,
                            ...(eventNames.length > 0 ? { event_names: eventNames } : {}),
                        }).url,
                        scopedEndpoint:
                            eventNames.length > 0
                                ? combineUrl(`api/projects/${teamId}/property_definitions`, {
                                      event_names: eventNames,
                                      is_feature_flag: false,
                                      filter_by_event_names: true,
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
                        excludedProperties: excludedProperties[TaxonomicFilterGroupType.EventProperties],
                        ...propertyTaxonomicGroupProps(),
                    },
                    {
                        name: 'Feature flags',
                        searchPlaceholder: 'feature flags',
                        type: TaxonomicFilterGroupType.EventFeatureFlags,
                        endpoint: combineUrl(`api/projects/${teamId}/property_definitions`, {
                            is_feature_flag: true,
                            ...(eventNames.length > 0 ? { event_names: eventNames } : {}),
                        }).url,
                        scopedEndpoint:
                            eventNames.length > 0
                                ? combineUrl(`api/projects/${teamId}/property_definitions`, {
                                      event_names: eventNames,
                                      is_feature_flag: true,
                                      filter_by_event_names: true,
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
                        excludedProperties: excludedProperties[TaxonomicFilterGroupType.EventFeatureFlags],
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
                        logic: featureFlags[FEATURE_FLAGS.PERSON_GROUPS_PROPERTY_DEFINITIONS]
                            ? undefined
                            : personPropertiesModel,
                        value: featureFlags[FEATURE_FLAGS.PERSON_GROUPS_PROPERTY_DEFINITIONS]
                            ? undefined
                            : 'personProperties',
                        endpoint: featureFlags[FEATURE_FLAGS.PERSON_GROUPS_PROPERTY_DEFINITIONS]
                            ? combineUrl(`api/projects/${teamId}/property_definitions`, {
                                  type: 'person',
                              }).url
                            : undefined,
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
                            return <IconCohort className="taxonomy-icon taxonomy-icon-muted" />
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
                            return <IconCohort className="taxonomy-icon taxonomy-icon-muted" />
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
                        endpoint: combineUrl(`api/projects/${teamId}/event_definitions`, {
                            event_type: EventDefinitionType.EventCustom,
                        }).url,
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
                    {
                        name: 'Sessions',
                        searchPlaceholder: 'sessions',
                        type: TaxonomicFilterGroupType.Sessions,
                        options: [
                            {
                                name: 'Session duration',
                                value: '$session_duration',
                            },
                        ],
                        getName: (option) => option.name,
                        getValue: (option) => option.value,
                        getPopupHeader: () => 'Session',
                    },
                    ...(featureFlags[FEATURE_FLAGS.HOGQL_EXPRESSIONS] ? [hogQl] : []),
                    ...groupAnalyticsTaxonomicGroups,
                    ...groupAnalyticsTaxonomicGroupNames,
                ]
            },
        ],
        activeTaxonomicGroup: [
            (s) => [s.activeTab, s.taxonomicGroups],
            (activeTab, taxonomicGroups) => taxonomicGroups.find((g) => g.type === activeTab),
        ],
        taxonomicGroupTypes: [
            (s, p) => [p.taxonomicGroupTypes, s.taxonomicGroups, s.featureFlags],
            (groupTypes, taxonomicGroups, featureFlags): TaxonomicFilterGroupType[] =>
                (groupTypes || taxonomicGroups.map((g) => g.type)).filter((type) => {
                    return (
                        type !== TaxonomicFilterGroupType.HogQLExpression ||
                        !!featureFlags[FEATURE_FLAGS.HOGQL_EXPRESSIONS]
                    )
                }),
        ],
        groupAnalyticsTaxonomicGroupNames: [
            (s) => [s.groupTypes, s.currentTeamId, s.aggregationLabel],
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
            (s) => [s.groupTypes, s.currentTeamId, s.aggregationLabel, s.featureFlags],
            (groupTypes, teamId, aggregationLabel, featureFlags): TaxonomicFilterGroup[] =>
                groupTypes.map((type) => ({
                    name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).singular)} properties`,
                    searchPlaceholder: `${aggregationLabel(type.group_type_index).singular} properties`,
                    type: `${TaxonomicFilterGroupType.GroupsPrefix}_${type.group_type_index}` as unknown as TaxonomicFilterGroupType,
                    logic: featureFlags[FEATURE_FLAGS.PERSON_GROUPS_PROPERTY_DEFINITIONS]
                        ? undefined
                        : groupPropertiesModel,
                    value: featureFlags[FEATURE_FLAGS.PERSON_GROUPS_PROPERTY_DEFINITIONS]
                        ? undefined
                        : `groupProperties_${type.group_type_index}`,
                    endpoint: featureFlags[FEATURE_FLAGS.PERSON_GROUPS_PROPERTY_DEFINITIONS]
                        ? combineUrl(`api/projects/${teamId}/property_definitions`, {
                              type: 'group',
                              group_type_index: type.group_type_index,
                          }).url
                        : undefined,
                    valuesEndpoint: (key) =>
                        `api/projects/${teamId}/groups/property_values/?${toParams({
                            key,
                            group_type_index: type.group_type_index,
                        })}`,
                    getName: (group) => group.name,
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
                    .filter((a) => !!a)
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

            // Update app-wide cached property metadata
            if (
                results.count > 0 &&
                (groupType === TaxonomicFilterGroupType.EventProperties ||
                    groupType === TaxonomicFilterGroupType.NumericalEventProperties)
            ) {
                updatePropertyDefinitions(results.results as PropertyDefinition[])
            }
        },
    }),
})
