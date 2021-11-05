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

export const taxonomicFilterLogic = kea<taxonomicFilterLogicType>({
    props: {} as TaxonomicFilterLogicProps,
    key: (props) => `${props.taxonomicFilterLogicKey}`,
    connect: { values: [teamLogic, ['currentTeamId'], groupsModel, ['groupTypes']] },
    actions: () => ({
        moveUp: true,
        moveDown: true,
        selectSelected: (onComplete?: () => void) => ({ onComplete }),
        enableMouseInteractions: true,
        tabLeft: true,
        tabRight: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setActiveTab: (activeTab: TaxonomicFilterGroupType) => ({ activeTab }),
        selectItem: (groupType: TaxonomicFilterGroupType, value: TaxonomicFilterValue | null, item: any) => ({
            groupType,
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
            (selectors) => [selectors.currentTeamId, selectors.groupAnalyticsTypes],
            (teamId, groupAnalyticsTypes): TaxonomicFilterGroup[] => [
                {
                    name: 'Events',
                    type: TaxonomicFilterGroupType.Events,
                    endpoint: `api/projects/${teamId}/event_definitions`,
                    getName: (eventDefinition: EventDefinition): string => eventDefinition.name,
                    getValue: (eventDefinition: EventDefinition): TaxonomicFilterValue => eventDefinition.name,
                },
                {
                    name: groupAnalyticsTypes[0]?.group_type,
                    type: `${TaxonomicFilterGroupType.Groups}_0`,
                    logic: groupPropertiesModel,
                    value: 'groupProperties_0',
                    getName: (group) => group.name,
                    getValue: (group) => group.name,
                },
                {
                    name: groupAnalyticsTypes[1]?.group_type,
                    type: `${TaxonomicFilterGroupType.Groups}_1`,
                    logic: groupPropertiesModel,
                    value: 'groupProperties_1',
                    getName: (group) => group.name,
                    getValue: (group) => group.name,
                },
                {
                    name: groupAnalyticsTypes[2]?.group_type,
                    type: `${TaxonomicFilterGroupType.Groups}_2`,
                    logic: groupPropertiesModel,
                    value: 'groupProperties_2',
                    getName: (group) => group.name,
                    getValue: (group) => group.name,
                },
                {
                    name: groupAnalyticsTypes[3]?.group_type,
                    type: `${TaxonomicFilterGroupType.Groups}_3`,
                    logic: groupPropertiesModel,
                    value: 'groupProperties_3',
                    getName: (group) => group.name,
                    getValue: (group) => group.name,
                },
                {
                    name: groupAnalyticsTypes[4]?.group_type,
                    type: `${TaxonomicFilterGroupType.Groups}_4`,
                    logic: groupPropertiesModel,
                    value: 'groupProperties_4',
                    getName: (group) => group.name,
                    getValue: (group) => group.name,
                },
                {
                    name: 'Actions',
                    type: TaxonomicFilterGroupType.Actions,
                    logic: actionsModel as any,
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
                    endpoint: `api/projects/${teamId}/property_definitions`,
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
                    name: 'Pageview URLs',
                    type: TaxonomicFilterGroupType.PageviewUrls,
                    endpoint: `api/projects/${teamId}/events/values/?key=$current_url`,
                    searchAlias: 'value',
                    getName: (option: SimpleOption): string => option.name,
                    getValue: (option: SimpleOption): TaxonomicFilterValue => option.name,
                },
                {
                    name: 'Screens',
                    type: TaxonomicFilterGroupType.Screens,
                    endpoint: `api/projects/${teamId}/events/values/?key=$screen_name`,
                    searchAlias: 'value',
                    getName: (option: SimpleOption): string => option.name,
                    getValue: (option: SimpleOption): TaxonomicFilterValue => option.name,
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
            ],
        ],
        taxonomicGroupTypes: [
            (selectors) => [(_, props) => props.taxonomicGroupTypes, selectors.taxonomicGroups],
            (groupTypes, taxonomicGroups): TaxonomicFilterGroupType[] =>
                groupTypes || taxonomicGroups.map((g) => g.type),
        ],
        value: [() => [(_, props) => props.value], (value) => value],
        groupType: [() => [(_, props) => props.groupType], (groupType) => groupType],
        currentTabIndex: [
            (s) => [s.taxonomicGroupTypes, s.activeTab],
            (groupTypes, activeTab) => Math.max(groupTypes.indexOf(activeTab || ''), 0),
        ],
        groupAnalyticsTypes: [(s) => [s.groupTypes], (groupTypes) => groupTypes],
    },

    listeners: ({ actions, values, props }) => ({
        selectItem: ({ groupType, value, item }) => {
            if (item && value) {
                const groupTypeWithGroupAnalytics = groupType.includes('groups')
                    ? TaxonomicFilterGroupType.Groups
                    : groupType
                props.onChange?.(groupTypeWithGroupAnalytics, value, item)
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
