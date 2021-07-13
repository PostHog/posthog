import { kea } from 'kea'
import { DisplayMode } from './TaxonomicPropertyFilter'
import { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { TaxonomicPropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { AnyPropertyFilter, PropertyOperator } from '~/types'
import { groups } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/groups'

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>({
    props: {} as TaxonomicPropertyFilterLogicProps,
    key: (props) => `${props.pageKey}-${props.filterIndex}`,

    connect: (props: TaxonomicPropertyFilterLogicProps) => ({
        values: [propertyFilterLogic(props), ['filters']],
    }),

    actions: () => ({
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setActiveTab: (activeTab: string) => ({ activeTab }),
        setDisplayMode: (displayMode: DisplayMode) => ({ displayMode }),
        selectItem: (type: string, id: string | number, name: string) => ({ type, id, name }),
    }),

    reducers: ({ selectors }) => ({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        activeTab: [
            (state: any) => {
                const type = selectors.filter(state)?.type
                return groups.find((g) => g.type === type)?.type || null
            },
            {
                setActiveTab: (_, { activeTab }) => activeTab,
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

    listeners: ({ actions, values, props }) => ({
        selectItem: ({ type, id, name }) => {
            if (type === 'cohort') {
                propertyFilterLogic(props).actions.setFilter(props.filterIndex, 'id', id, null, type)
            } else {
                const { operator } = values.filter || {}
                const newOperator = name === '$active_feature_flags' ? PropertyOperator.IContains : operator

                propertyFilterLogic(props).actions.setFilter(
                    props.filterIndex,
                    name,
                    null, // Reset value field
                    newOperator || PropertyOperator.Exact,
                    type
                )
                actions.setDisplayMode(DisplayMode.OPERATOR_VALUE_SELECT)
            }
        },
    }),
})
