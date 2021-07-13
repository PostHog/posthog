import { kea } from 'kea'
import { DisplayMode } from './TaxonomicPropertyFilter'
import { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { TaxonomicPropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { AnyPropertyFilter } from '~/types'

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
        setDisplayMode: (displayMode: DisplayMode) => ({ displayMode }),
    }),

    reducers: ({ selectors }) => ({
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
        displayMode: [
            // this works because:
            // 1. you can use selectors for defaults
            // 2. the filter selector asks for data that's stored outside this logic
            (state: any) => {
                const { key, type } = selectors.filter(state) || {}
                return key && type !== 'cohort' ? DisplayMode.OPERATOR_VALUE_SELECT : DisplayMode.PROPERTY_SELECT
            },
            {
                setDisplayMode: (_, { displayMode }) => displayMode,
            },
        ],
    }),

    selectors: {
        filter: [
            (s) => [s.filters, (_, props) => props.filterIndex],
            (filters, filterIndex): AnyPropertyFilter | null => filters[filterIndex] || null,
        ],
    },
})
