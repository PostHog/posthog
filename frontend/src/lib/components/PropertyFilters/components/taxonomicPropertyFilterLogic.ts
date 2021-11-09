import { kea } from 'kea'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { TaxonomicPropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { AnyPropertyFilter, PropertyFilterValue, PropertyOperator } from '~/types'
import { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'
import { cohortsModel } from '~/models/cohortsModel'

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>({
    path: (key) => ['lib', 'components', 'PropertyFilters', 'components', 'taxonomicPropertyFilterLogic', key],
    props: {} as TaxonomicPropertyFilterLogicProps,
    key: (props) => `${props.pageKey}-${props.filterIndex}`,

    connect: (props: TaxonomicPropertyFilterLogicProps) => ({
        values: [propertyFilterLogic(props), ['filters']],
    }),

    actions: {
        selectItem: (propertyType?: string, propertyKey?: PropertyFilterValue) => ({ propertyType, propertyKey }),
        openDropdown: true,
        closeDropdown: true,
    },

    reducers: {
        dropdownOpen: [
            false,
            {
                openDropdown: () => true,
                closeDropdown: () => false,
            },
        ],
    },

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
        selectItem: ({ propertyType, propertyKey }) => {
            if (propertyKey && propertyType) {
                if (propertyType === 'cohort') {
                    propertyFilterLogic(props).actions.setFilter(
                        props.filterIndex,
                        'id',
                        propertyKey,
                        null,
                        propertyType
                    )
                } else {
                    const operator =
                        propertyKey === '$active_feature_flags'
                            ? PropertyOperator.IContains
                            : values.filter?.operator || PropertyOperator.Exact

                    propertyFilterLogic(props).actions.setFilter(
                        props.filterIndex,
                        propertyKey.toString(),
                        null, // Reset value field
                        operator,
                        propertyType
                    )
                }
                actions.closeDropdown()
            }
        },
    }),
})
