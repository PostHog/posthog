import { kea } from 'kea'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { UniversalSearchGroup, UniversalSearchGroupType, UniversalSearchLogicProps, ListStorage } from './types'
import { searchListLogic } from 'lib/components/UniversalSearch/searchListLogic'
import {
    ActionType,
    CohortType,
    DashboardType,
    EventDefinition,
    Experiment,
    FeatureFlagType,
    Group,
    InsightModel,
    PersonType,
    PluginType,
} from '~/types'
import { cohortsModel } from '~/models/cohortsModel'
import { actionsModel } from '~/models/actionsModel'
import { teamLogic } from 'scenes/teamLogic'
import { groupsModel } from '~/models/groupsModel'
import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { capitalizeFirstLetter } from 'lib/utils'
import { combineUrl } from 'kea-router'

import { universalSearchLogicType } from './universalSearchLogicType'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { dashboardsModel } from '~/models/dashboardsModel'

export const universalSearchLogic = kea<universalSearchLogicType>({
    path: (key) => ['lib', 'components', 'UniversalSearch', 'universalSearchLogic', key],
    props: {} as UniversalSearchLogicProps,
    key: () => `universal-search`,
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
        searchListResultsReceived: (groupType: UniversalSearchGroupType, results: ListStorage) => ({
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
                return selectors.groupType(state) || selectors.searchGroupTypes(state)[0]
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
        searchGroups: [
            (selectors) => [selectors.currentTeamId, selectors.groupAnalyticsTaxonomicGroups],
            (teamId, groupAnalyticsTaxonomicGroups): UniversalSearchGroup[] => [
                {
                    name: 'Events',
                    searchPlaceholder: 'events',
                    type: UniversalSearchGroupType.Events,
                    endpoint: `api/projects/${teamId}/event_definitions`,
                    getName: (eventDefinition: EventDefinition) => eventDefinition.name,
                    getValue: (eventDefinition: EventDefinition) => eventDefinition.name,
                },
                {
                    name: 'Actions',
                    searchPlaceholder: 'actions',
                    type: UniversalSearchGroupType.Actions,
                    logic: actionsModel,
                    value: 'actions',
                    getName: (action: ActionType) => action.name || '',
                    getValue: (action: ActionType) => action.id,
                },
                {
                    name: 'Persons',
                    searchPlaceholder: 'persons',
                    type: UniversalSearchGroupType.Persons,
                    endpoint: `api/projects/${teamId}/persons/`,
                    getName: (person: PersonType) => person.name || 'Anon user?',
                    getValue: (person: PersonType) => person.distinct_ids[0],
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
                },
                {
                    name: 'Cohorts',
                    searchPlaceholder: 'cohorts',
                    type: UniversalSearchGroupType.Cohorts,
                    logic: cohortsModel,
                    value: 'cohorts',
                    getName: (cohort: CohortType) => cohort.name || `Cohort ${cohort.id}`,
                    getValue: (cohort: CohortType) => cohort.id,
                },
                {
                    name: 'Feature Flags',
                    searchPlaceholder: 'feature flags',
                    type: UniversalSearchGroupType.FeatureFlags,
                    logic: featureFlagsLogic,
                    value: 'featureFlags',
                    getName: (featureFlag: FeatureFlagType) => featureFlag.name || featureFlag.key,
                    getValue: (featureFlag: FeatureFlagType) => featureFlag.id || '',
                },
                {
                    name: 'Experiments',
                    searchPlaceholder: 'experiments',
                    type: UniversalSearchGroupType.Experiments,
                    logic: experimentsLogic,
                    value: 'experiments',
                    getName: (experiment: Experiment) => experiment.name,
                    getValue: (experiment: Experiment) => experiment.id,
                },
                {
                    name: 'Plugins',
                    searchPlaceholder: 'plugins',
                    type: UniversalSearchGroupType.Plugins,
                    logic: pluginsLogic,
                    value: 'allPossiblePlugins',
                    getName: (plugin: Pick<PluginType, 'name' | 'url'>) => plugin.name,
                    getValue: (plugin: Pick<PluginType, 'name' | 'url'>) => plugin.name,
                },
                {
                    name: 'Dashboards',
                    searchPlaceholder: 'dashboards',
                    type: UniversalSearchGroupType.Dashboards,
                    logic: dashboardsModel,
                    value: 'nameSortedDashboards',
                    getName: (dashboard: DashboardType) => dashboard.name,
                    getValue: (dashboard: DashboardType) => dashboard.id,
                },
                {
                    name: 'Dashboards',
                    searchPlaceholder: 'dashboards',
                    type: UniversalSearchGroupType.Dashboards,
                    logic: dashboardsModel,
                    value: 'nameSortedDashboards',
                    getName: (dashboard: DashboardType) => dashboard.name,
                    getValue: (dashboard: DashboardType) => dashboard.id,
                },
                ...groupAnalyticsTaxonomicGroups,
            ],
        ],
        activeTaxonomicGroup: [
            (s) => [s.activeTab, s.searchGroups],
            (activeTab, searchGroups) => searchGroups.find((g) => g.type === activeTab),
        ],
        searchGroupTypes: [
            (selectors) => [(_, props) => props.searchGroupTypes, selectors.searchGroups],
            (groupTypes, searchGroups): UniversalSearchGroupType[] => groupTypes || searchGroups.map((g) => g.type),
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
                    groupTypeIndex: type.group_type_index,
                })),
        ],
        searchListLogics: [
            (s) => [s.searchGroupTypes, (_, props) => props],
            (searchGroupTypes, props): Record<string, ReturnType<typeof searchListLogic.build>> =>
                Object.fromEntries(
                    searchGroupTypes.map((groupType) => [
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
                        Object.entries(s.searchListLogics(state, props)).map(([groupType, logic]) => [
                            groupType,
                            logic.isMounted() ? logic.selectors.totalResultCount(state, logic.props) : 0,
                        ])
                    ),
            ],
            (infiniteListCounts) => infiniteListCounts,
        ],
        value: [() => [(_, props) => props.value], (value) => value],
        groupType: [() => [(_, props) => props.groupType], (groupType) => groupType],
        currentTabIndex: [
            (s) => [s.searchGroupTypes, s.activeTab],
            (groupTypes, activeTab) => Math.max(groupTypes.indexOf(activeTab || ''), 0),
        ],
        searchPlaceholder: [
            (s) => [s.searchGroups, s.searchGroupTypes],
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
            const { currentTabIndex, searchGroupTypes, infiniteListCounts } = values
            for (let i = 1; i < searchGroupTypes.length; i++) {
                const newIndex = (currentTabIndex - i + searchGroupTypes.length) % searchGroupTypes.length
                if (infiniteListCounts[searchGroupTypes[newIndex]] > 0) {
                    actions.setActiveTab(searchGroupTypes[newIndex])
                    return
                }
            }
        },

        tabRight: () => {
            const { currentTabIndex, searchGroupTypes, infiniteListCounts } = values
            for (let i = 1; i < searchGroupTypes.length; i++) {
                const newIndex = (currentTabIndex + i) % searchGroupTypes.length
                if (infiniteListCounts[searchGroupTypes[newIndex]] > 0) {
                    actions.setActiveTab(searchGroupTypes[newIndex])
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

        searchListResultsReceived: ({ groupType, results }) => {
            // Open the next tab if no results on an active tab.
            if (groupType === values.activeTab && !results.count) {
                actions.tabRight()
            }
        },
    }),
})
