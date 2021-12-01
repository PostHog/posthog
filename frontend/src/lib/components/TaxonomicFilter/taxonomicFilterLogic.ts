import { kea } from 'kea'
import { taxonomicFilterLogicType } from './taxonomicFilterLogicType'
import {
    SimpleOption,
    TaxonomicFilterGroupType,
    TaxonomicFilterGroup,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { ActionType, CohortType, EventDefinition, PersonProperty, PropertyDefinition } from '~/types'
import { cohortsModel } from '~/models/cohortsModel'
import { actionsModel } from '~/models/actionsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { teamLogic } from '../../../scenes/teamLogic'
import { groupsModel } from '~/models/groupsModel'
import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { capitalizeFirstLetter, toParams } from 'lib/utils'

export const taxonomicFilterLogic = kea<taxonomicFilterLogicType>({
    path: (key) => ['lib', 'components', 'TaxonomicFilter', 'taxonomicFilterLogic', key],
    props: {} as TaxonomicFilterLogicProps,
    key: (props) => `${props.taxonomicFilterLogicKey}`,
    connect: {
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes'],
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

    selectors: {
        taxonomicFilterLogicKey: [
            () => [(_, props) => props.taxonomicFilterLogicKey],
            (taxonomicFilterLogicKey) => taxonomicFilterLogicKey,
        ],
        taxonomicGroups: [
            (selectors) => [selectors.currentTeamId, selectors.groupAnalyticsTaxonomicGroups],
            (teamId, groupAnalyticsTaxonomicGroups): TaxonomicFilterGroup[] => [
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
                    logic: actionsModel as any,
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
                    endpoint: `api/projects/${teamId}/property_definitions`,
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
        taxonomicGroupTypes: [
            (selectors) => [(_, props) => props.taxonomicGroupTypes, selectors.taxonomicGroups],
            (groupTypes, taxonomicGroups): TaxonomicFilterGroupType[] =>
                groupTypes || taxonomicGroups.map((g) => g.type),
        ],
        groupAnalyticsTaxonomicGroups: [
            (selectors) => [selectors.groupTypes, selectors.currentTeamId],
            (groupTypes, teamId): TaxonomicFilterGroup[] =>
                groupTypes.map((type, index) => ({
                    name: capitalizeFirstLetter(type.group_type),
                    searchPlaceholder: `${type.group_type} properties`,
                    type: `${TaxonomicFilterGroupType.GroupsPrefix}_${index}` as TaxonomicFilterGroupType,
                    logic: groupPropertiesModel,
                    value: `groupProperties_${index}`,
                    valuesEndpoint: (key) =>
                        `api/projects/${teamId}/groups/property_values/?${toParams({ key, group_type_index: index })}`,
                    getName: (group) => capitalizeFirstLetter(group.name),
                    getValue: (group) => group.name,
                    groupTypeIndex: index,
                })),
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
            const { currentTabIndex, taxonomicGroupTypes } = values
            const newIndex = (currentTabIndex - 1 + taxonomicGroupTypes.length) % taxonomicGroupTypes.length
            actions.setActiveTab(taxonomicGroupTypes[newIndex])
        },

        tabRight: () => {
            const { currentTabIndex, taxonomicGroupTypes } = values
            const newIndex = (currentTabIndex + 1) % taxonomicGroupTypes.length
            actions.setActiveTab(taxonomicGroupTypes[newIndex])
        },
    }),
})
