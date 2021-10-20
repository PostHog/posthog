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

export const taxonomicFilterLogic = kea<taxonomicFilterLogicType>({
    props: {} as TaxonomicFilterLogicProps,
    key: (props) => `${props.taxonomicFilterLogicKey}`,
    connect: { values: [teamLogic, ['currentTeamId']] },
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
                return selectors.groupType(state) || selectors.groupTypes(state)[0]
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
        groups: [
            (selectors) => [selectors.currentTeamId],
            (teamId): TaxonomicFilterGroup[] => [
                {
                    name: 'Events',
                    type: TaxonomicFilterGroupType.Events,
                    endpoint: `api/projects/${teamId}/event_definitions`,
                    getName: (eventDefinition: EventDefinition): string => eventDefinition.name,
                    getValue: (eventDefinition: EventDefinition): TaxonomicFilterValue => eventDefinition.name,
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
        groupTypes: [
            (selectors) => [(_, props) => props.groupTypes, selectors.groups],
            (groupTypes, groups): TaxonomicFilterGroupType[] => groupTypes || groups.map((g) => g.type),
        ],
        value: [() => [(_, props) => props.value], (value) => value],
        groupType: [() => [(_, props) => props.groupType], (groupType) => groupType],
        currentTabIndex: [
            (s) => [s.groupTypes, s.activeTab],
            (groupTypes, activeTab) => Math.max(groupTypes.indexOf(activeTab || ''), 0),
        ],
    },

    listeners: ({ actions, values, props }) => ({
        selectItem: ({ groupType, value, item }) => {
            if (item && value) {
                props.onChange?.(groupType, value, item)
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
            const { currentTabIndex, groupTypes } = values
            const newIndex = (currentTabIndex - 1 + groupTypes.length) % groupTypes.length
            actions.setActiveTab(groupTypes[newIndex])
        },

        tabRight: () => {
            const { currentTabIndex, groupTypes } = values
            const newIndex = (currentTabIndex + 1) % groupTypes.length
            actions.setActiveTab(groupTypes[newIndex])
        },
    }),
})
