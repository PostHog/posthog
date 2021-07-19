import { kea } from 'kea'
import { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { TaxonomicPropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { AnyPropertyFilter, PropertyOperator } from '~/types'
import { groups } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/groups'
import { cohortsModel } from '~/models/cohortsModel'
import { infiniteListLogic } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/infiniteListLogic'

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>({
    props: {} as TaxonomicPropertyFilterLogicProps,
    key: (props) => `${props.pageKey}-${props.filterIndex}`,

    connect: (props: TaxonomicPropertyFilterLogicProps) => ({
        values: [propertyFilterLogic(props), ['filters']],
    }),

    actions: () => ({
        moveUp: true,
        moveDown: true,
        selectSelected: (onComplete?: () => void) => ({ onComplete }),
        enableMouseInteractions: true,
        tabLeft: true,
        tabRight: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setActiveTab: (activeTab: string) => ({ activeTab }),
        selectItem: (type: string, id: string | number, name: string) => ({ type, id, name }),
        openDropdown: true,
        closeDropdown: true,
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
            (state: any) => {
                const type = selectors.filter(state)?.type
                return groups.find((g) => g.type === type)?.type || groups[0]?.type
            },
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
        dropdownOpen: [
            false,
            {
                openDropdown: () => true,
                closeDropdown: () => false,
            },
        ],
        mouseInteractionsEnabled: [
            // This fixes a bug with keyboard up/down scrolling when the mouse is over the list.
            // Otherwise shifting list elements cause the "hover" action to be triggered randomly.
            true,
            {
                moveUp: () => false,
                moveDown: () => false,
                setActiveTab: () => true, // reset immediately if clicked on a tab
                enableMouseInteractions: () => true, // called 100ms after up/down
            },
        ],
    }),

    selectors: {
        tabs: [() => [], () => groups.map((g) => g.type)],
        currentTabIndex: [
            (s) => [s.tabs, s.activeTab],
            (tabs, activeTab) => Math.max(tabs.indexOf(activeTab || ''), 0),
        ],
        filter: [
            (s) => [s.filters, (_, props) => props.filterIndex],
            (filters, filterIndex): AnyPropertyFilter | null => filters[filterIndex] || null,
        ],
        selectedCohortName: [
            (s) => [s.filter, cohortsModel.selectors.cohorts],
            (filter, cohorts) => (filter?.type === 'cohort' ? cohorts.find((c) => c.id === filter?.value)?.name : null),
        ],
    },

    listeners: ({ actions, values, props }) => ({
        selectItem: ({ type, id, name }) => {
            if (type === 'cohort') {
                propertyFilterLogic(props).actions.setFilter(props.filterIndex, 'id', id, null, type)
            } else {
                const operator =
                    name === '$active_feature_flags'
                        ? PropertyOperator.IContains
                        : values.filter?.operator || PropertyOperator.Exact

                propertyFilterLogic(props).actions.setFilter(
                    props.filterIndex,
                    name,
                    null, // Reset value field
                    operator,
                    type
                )
            }
            actions.closeDropdown()
        },

        moveUp: async (_, breakpoint) => {
            if (values.activeTab) {
                infiniteListLogic({ ...props, type: values.activeTab }).actions.moveUp()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        moveDown: async (_, breakpoint) => {
            if (values.activeTab) {
                infiniteListLogic({ ...props, type: values.activeTab }).actions.moveDown()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        selectSelected: async ({ onComplete }, breakpoint) => {
            if (values.activeTab) {
                infiniteListLogic({ ...props, type: values.activeTab }).actions.selectSelected(onComplete)
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        tabLeft: () => {
            const newIndex = (values.currentTabIndex - 1 + groups.length) % groups.length
            actions.setActiveTab(groups[newIndex].type)
        },

        tabRight: () => {
            const newIndex = (values.currentTabIndex + 1) % groups.length
            actions.setActiveTab(groups[newIndex].type)
        },
    }),
})
