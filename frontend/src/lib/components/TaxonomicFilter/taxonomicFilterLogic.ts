import { kea } from 'kea'
import { taxonomicFilterLogicType } from './taxonomicFilterLogicType'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { taxonomicGroupsLogic } from 'lib/components/TaxonomicFilter/taxonomicGroupsLogic'

export const taxonomicFilterLogic = kea<taxonomicFilterLogicType>({
    props: {} as TaxonomicFilterLogicProps,
    key: (props) => `${props.taxonomicFilterLogicKey}`,

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
        groupTypes: [
            () => [
                (_, props) => props.groupTypes,
                (_, props) => props.groupAnalytics,
                taxonomicGroupsLogic.selectors.groups,
            ],
            (groupTypes, groupAnalytics, groups: TaxonomicFilterGroup[]): TaxonomicFilterGroupType[] => {
                let taxonomicGroupTypes = groupTypes || groups.map((g) => g.type)
                if (groupTypes && groupAnalytics) {
                    taxonomicGroupTypes = [
                        taxonomicGroupTypes[0],
                        taxonomicGroupTypes[1],
                        ...groups.filter((info) => info.groupAnalytics).map((info) => info.type),
                        ...taxonomicGroupTypes.slice(2),
                    ]
                }
                return taxonomicGroupTypes
            },
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
