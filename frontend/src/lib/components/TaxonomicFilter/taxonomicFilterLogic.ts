import { kea } from 'kea'
import { taxonomicFilterLogicType } from './taxonomicFilterLogicType'
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
import { ActionType, CohortType, EventDefinition, PersonProperty, PropertyDefinition } from '~/types'
import { cohortsModel } from '~/models/cohortsModel'
import { actionsModel } from '~/models/actionsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { teamLogic } from 'scenes/teamLogic'
import { groupsModel } from '~/models/groupsModel'
import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { capitalizeFirstLetter, toParams } from 'lib/utils'
import { combineUrl } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const taxonomicFilterLogic = kea<taxonomicFilterLogicType>({
    path: (key) => ['lib', 'components', 'TaxonomicFilter', 'taxonomicFilterLogic', key],
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
                selectItem: () => '',
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
        eventNames: [() => [(_, props) => props.eventNames], (eventNames) => eventNames],
        taxonomicGroups: [
            (selectors) => [
                selectors.currentTeamId,
                selectors.groupAnalyticsTaxonomicGroups,
                selectors.eventNames,
                featureFlagLogic.selectors.featureFlags,
            ],
            (teamId, groupAnalyticsTaxonomicGroups, eventNames, featureFlags): TaxonomicFilterGroup[] => [
                {
                    name: 'Events',
                    searchPlaceholder: 'events',
                    type: TaxonomicFilterGroupType.Events,
                    endpoint: `api/projects/${teamId}/event_definitions`,
                    getName: (eventDefinition: EventDefinition): string => eventDefinition.name,
                    getValue: (eventDefinition: EventDefinition): TaxonomicFilterValue => eventDefinition.name,
                },
                {
                    name: 'Actions',
                    searchPlaceholder: 'actions',
                    type: TaxonomicFilterGroupType.Actions,
                    logic: actionsModel,
                    value: 'actions',
                    getName: (action: ActionType): string => action.name,
                    getValue: (action: ActionType): TaxonomicFilterValue => action.id,
                },
                {
                    name: 'Autocapture elements',
                    searchPlaceholder: 'autocapture elements',
                    type: TaxonomicFilterGroupType.Elements,
                    options: ['tag_name', 'text', 'href', 'selector'].map((option) => ({
                        name: option,
                    })) as SimpleOption[],
                    getName: (option: SimpleOption): string => option.name,
                    getValue: (option: SimpleOption): TaxonomicFilterValue => option.name,
                },
                {
                    name: 'Event properties',
                    searchPlaceholder: 'event properties',
                    type: TaxonomicFilterGroupType.EventProperties,
                    endpoint: combineUrl(
                        `api/projects/${teamId}/property_definitions`,
                        featureFlags[FEATURE_FLAGS.UNSEEN_EVENT_PROPERTIES] ? { event_names: eventNames } : {}
                    ).url,
                    getName: (propertyDefinition: PropertyDefinition): string => propertyDefinition.name,
                    getValue: (propertyDefinition: PropertyDefinition): TaxonomicFilterValue => propertyDefinition.name,
                },
                {
                    name: 'Person properties',
                    searchPlaceholder: 'person properties',
                    type: TaxonomicFilterGroupType.PersonProperties,
                    logic: personPropertiesModel,
                    value: 'personProperties',
                    getName: (personProperty: PersonProperty): string => personProperty.name,
                    getValue: (personProperty: PersonProperty): TaxonomicFilterValue => personProperty.name,
                },
                {
                    name: 'Cohorts',
                    searchPlaceholder: 'cohorts',
                    type: TaxonomicFilterGroupType.Cohorts,
                    logic: cohortsModel,
                    value: 'cohorts',
                    getName: (cohort: CohortType): string => cohort.name || `Cohort ${cohort.id}`,
                    getValue: (cohort: CohortType): TaxonomicFilterValue => cohort.id,
                },
                {
                    name: 'Cohorts',
                    searchPlaceholder: 'cohorts',
                    type: TaxonomicFilterGroupType.CohortsWithAllUsers,
                    logic: cohortsModel,
                    value: 'cohortsWithAllUsers',
                    getName: (cohort: CohortType): string => cohort.name || `Cohort ${cohort.id}`,
                    getValue: (cohort: CohortType): TaxonomicFilterValue => cohort.id,
                },
                {
                    name: 'Pageview URLs',
                    searchPlaceholder: 'pageview URLs',
                    type: TaxonomicFilterGroupType.PageviewUrls,
                    endpoint: `api/projects/${teamId}/events/values/?key=$current_url`,
                    searchAlias: 'value',
                    getName: (option: SimpleOption): string => option.name,
                    getValue: (option: SimpleOption): TaxonomicFilterValue => option.name,
                },
                {
                    name: 'Screens',
                    searchPlaceholder: 'screens',
                    type: TaxonomicFilterGroupType.Screens,
                    endpoint: `api/projects/${teamId}/events/values/?key=$screen_name`,
                    searchAlias: 'value',
                    getName: (option: SimpleOption): string => option.name,
                    getValue: (option: SimpleOption): TaxonomicFilterValue => option.name,
                },
                {
                    name: 'Custom Events',
                    searchPlaceholder: 'custom events',
                    type: TaxonomicFilterGroupType.CustomEvents,
                    logic: eventDefinitionsModel,
                    value: 'customEvents',
                    getName: (eventDefinition: EventDefinition): string => eventDefinition.name,
                    getValue: (eventDefinition: EventDefinition): TaxonomicFilterValue => eventDefinition.name,
                },
                {
                    name: 'Wildcards',
                    searchPlaceholder: 'wildcards',
                    type: TaxonomicFilterGroupType.Wildcards,
                    // Populated via optionsFromProp
                    getName: (option: SimpleOption): string => option.name,
                    getValue: (option: SimpleOption): TaxonomicFilterValue => option.name,
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
            (groupTypes, taxonomicGroups): TaxonomicFilterGroupType[] =>
                groupTypes || taxonomicGroups.map((g) => g.type),
        ],
        groupAnalyticsTaxonomicGroups: [
            (selectors) => [selectors.groupTypes, selectors.currentTeamId, selectors.aggregationLabel],
            (groupTypes, teamId, aggregationLabel): TaxonomicFilterGroup[] =>
                groupTypes.map((type) => ({
                    name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).singular)} properties`,
                    searchPlaceholder: `${aggregationLabel(type.group_type_index).singular} properties`,
                    type: `${TaxonomicFilterGroupType.GroupsPrefix}_${type.group_type_index}` as TaxonomicFilterGroupType,
                    logic: groupPropertiesModel,
                    value: `groupProperties_${type.group_type_index}`,
                    valuesEndpoint: (key) =>
                        `api/projects/${teamId}/groups/property_values/?${toParams({
                            key,
                            group_type_index: type.group_type_index,
                        })}`,
                    getName: () => capitalizeFirstLetter(aggregationLabel(type.group_type_index).singular),
                    getValue: (group) => group.name,
                    groupTypeIndex: type.group_type_index,
                })),
        ],
        infiniteListLogics: [
            (s) => [s.taxonomicGroupTypes, (_, props) => props],
            (taxonomicGroupTypes, props): Record<string, ReturnType<typeof infiniteListLogic.build>> =>
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
        totalCounts: [
            (s) => [
                (state, props) =>
                    Object.fromEntries(
                        Object.entries(s.infiniteListLogics(state, props)).map(([groupType, logic]) => [
                            groupType,
                            logic.isMounted() ? logic.selectors.totalCount(state, logic.props) : 0,
                        ])
                    ),
            ],
            (totalCounts) => totalCounts,
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
                        (type) => !type.startsWith(TaxonomicFilterGroupType.GroupsPrefix)
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
            const { currentTabIndex, taxonomicGroupTypes, totalCounts } = values
            for (let i = 1; i < taxonomicGroupTypes.length; i++) {
                const newIndex = (currentTabIndex - i + taxonomicGroupTypes.length) % taxonomicGroupTypes.length
                if (totalCounts[taxonomicGroupTypes[newIndex]] > 0) {
                    actions.setActiveTab(taxonomicGroupTypes[newIndex])
                    return
                }
            }
        },

        tabRight: () => {
            const { currentTabIndex, taxonomicGroupTypes, totalCounts } = values
            for (let i = 1; i < taxonomicGroupTypes.length; i++) {
                const newIndex = (currentTabIndex + i) % taxonomicGroupTypes.length
                if (totalCounts[taxonomicGroupTypes[newIndex]] > 0) {
                    actions.setActiveTab(taxonomicGroupTypes[newIndex])
                    return
                }
            }
        },

        setSearchQuery: () => {
            const { activeTaxonomicGroup, totalCounts } = values

            // Taxonomic group with a local data source, zero results after searching.
            // Open the next tab.
            if (
                activeTaxonomicGroup &&
                !activeTaxonomicGroup.endpoint &&
                totalCounts[activeTaxonomicGroup.type] === 0
            ) {
                actions.tabRight()
            }
        },

        infiniteListResultsReceived: ({ groupType, results }) => {
            // Open the next tab if no results on an active tab.
            if (groupType === values.activeTab && results.count === 0) {
                actions.tabRight()
            }
        },
    }),
})
