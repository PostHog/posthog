import { kea } from 'kea'
import { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { TaxonomicPropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { AnyPropertyFilter, PropertyOperator } from '~/types'
import { groups } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter/groups'
import { cohortsModel } from '~/models/cohortsModel'

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>({
    props: {} as TaxonomicPropertyFilterLogicProps,
    key: (props) => `${props.pageKey}-${props.filterIndex}`,

    connect: (props: TaxonomicPropertyFilterLogicProps) => ({
        values: [propertyFilterLogic(props), ['filters']],
    }),

    actions: () => ({
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
        dropdownOpen: [
            false,
            {
                openDropdown: () => true,
                closeDropdown: () => false,
            },
        ],
    }),

    selectors: {
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
    }),
})
