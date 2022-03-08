import { kea } from 'kea'

import { PropertyGroupFilter, FilterLogicalOperator } from '~/types'
import { PropertyGroupFilterLogicProps } from 'lib/components/PropertyFilters/types'

import { propertyGroupFilterLogicType } from './propertyGroupFilterLogicType'
import { convertPropertiesToPropertyGroup } from 'lib/utils'

export const propertyGroupFilterLogic = kea<propertyGroupFilterLogicType>({
    path: (key) => ['lib', 'components', 'PropertyGroupFilters', 'propertyGroupFilterLogic', key],
    props: {} as PropertyGroupFilterLogicProps,
    key: (props) => props.pageKey,

    actions: () => ({
        update: (propertyGroupIndex?: number) => ({ propertyGroupIndex }),
        setFilters: (filters: PropertyGroupFilter) => ({ filters }),
        removeFilterGroup: (filterGroup: number) => ({ filterGroup }),
        setOuterPropertyGroupsType: (type: FilterLogicalOperator) => ({ type }),
        setPropertyFilters: (properties, index: number) => ({ properties, index }),
        setInnerPropertyGroupType: (type: FilterLogicalOperator, index: number) => ({ type, index }),
        duplicateFilterGroup: (propertyGroupIndex: number) => ({ propertyGroupIndex }),
        addFilterGroup: true,
    }),

    reducers: ({ props }) => ({
        filters: [
            props.propertyFilters
                ? convertPropertiesToPropertyGroup(props.propertyFilters)
                : ({} as PropertyGroupFilter),
            {
                setFilters: (_, { filters }) => filters,
                addFilterGroup: (state) => {
                    if (!state.values) {
                        return {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [{}],
                                },
                            ],
                        }
                    }
                    const filterGroups = [...state.values, { type: FilterLogicalOperator.And, values: [{}] }]

                    return { ...state, values: filterGroups }
                },
                removeFilterGroup: (state, { filterGroup }) => {
                    const filteredGroups = [...state.values]
                    filteredGroups.splice(filterGroup, 1)
                    return { ...state, values: filteredGroups }
                },
                setOuterPropertyGroupsType: (state, { type }) => {
                    return { ...state, type }
                },
                setPropertyFilters: (state, { properties, index }) => {
                    const values = [...state.values]
                    values[index] = { ...values[index], values: properties }

                    return { ...state, values }
                },
                setInnerPropertyGroupType: (state, { type, index }) => {
                    const values = [...state.values]
                    values[index] = { ...values[index], type }
                    return { ...state, values }
                },
            },
        ],
    }),
    listeners: ({ actions, props, values }) => ({
        setFilters: () => actions.update(),
        setPropertyFilters: () => actions.update(),
        setInnerPropertyGroupType: () => actions.update(),
        setOuterPropertyGroupsType: () => actions.update(),
        removeFilterGroup: () => actions.update(),
        addFilterGroup: () => actions.update(),
        update: () => {
            props.onChange(values.filters)
        },
    }),

    selectors: {
        filledFilters: [(s) => [s.filters], (filters) => filters],
        filtersWithNew: [(s) => [s.filters], (filters) => filters],
    },
})
