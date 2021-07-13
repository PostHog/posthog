import { kea, Selector } from 'kea'
import { DisplayMode } from './TaxonomicPropertyFilter'
import { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { TaxonomicPropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { groups } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/groups'

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>({
    props: {} as TaxonomicPropertyFilterLogicProps,
    key: (props) => `${props.pageKey}-${props.filterIndex}`,

    connect: (props: TaxonomicPropertyFilterLogicProps) => ({
        values: [propertyFilterLogic(props), ['filters']],
    }),

    actions: () => ({
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setSelectedItemKey: (selectedItemKey: string | number | null) => ({ selectedItemKey }),
        setActiveTabKey: (activeTabKey: string) => ({ activeTabKey }),
    }),

    reducers: {
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        selectedItemKey: [
            null as string | number | null,
            {
                setSelectedItemKey: (_, { selectedItemKey }) => selectedItemKey,
            },
        ],
        activeTabKey: [
            null as string | null,
            {
                setActiveTabKey: (_, { activeTabKey }) => activeTabKey,
            },
        ],
    },

    selectors: {
        displayMode: [
            (s) => [s.filters, (_, props) => props.filterIndex],
            (filters, filterIndex) => {
                const { key, type } = filters[filterIndex] || {}
                return key && type !== 'cohort' ? DisplayMode.OPERATOR_VALUE_SELECT : DisplayMode.PROPERTY_SELECT
            },
        ],
        localGroupCounts: [
            () =>
                groups
                    .filter(({ logic }) => !!logic)
                    .map(({ logic, value }) => (state, props) =>
                        logic && value ? logic(props).selectors[value](state) || [] : []
                    ) as [Selector, Selector], // mocking the type
            (args: Record<string, any>[][]) => {
                return Object.fromEntries(
                    groups.filter(({ logic }) => !!logic).map(({ key }, index) => [key, args[index].length])
                )
            },
        ],
        counts: [(s) => [s.localGroupCounts], (localGroupCounts) => localGroupCounts],
    },
})
