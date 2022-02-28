import { kea } from 'kea'

import { AndOrPropertyFilter, FilterLogicalOperator } from '~/types'
import { parsePropertyGroups } from 'lib/components/PropertyFilters/utils'
import { PropertyGroupFilterLogicProps } from 'lib/components/PropertyFilters/types'

import { propertyGroupFilterLogicType } from './propertyGroupFilterLogicType'
import clone from 'clone'

export const propertyGroupFilterLogic = kea<propertyGroupFilterLogicType>({
    path: (key) => ['lib', 'components', 'PropertyGroupFilters', 'propertyGroupFilterLogic', key],
    props: {} as PropertyGroupFilterLogicProps,
    key: (props) => props.pageKey,

    actions: () => ({
        update: (propertyGroupIndex?: number) => ({ propertyGroupIndex }),
        setFilters: (filters: AndOrPropertyFilter) => ({ filters }),
        removeFilterGroup: (filterGroup: number) => ({ filterGroup }),
        setPropertyGroupsType: (type: FilterLogicalOperator) => ({ type }),
        setPropertyFilters: (properties, index: number) => ({ properties, index }),
        setPropertyGroupType: (type: FilterLogicalOperator, index: number) => ({ type, index }),
        addFilterGroup: true,
    }),

    reducers: ({ props }) => ({
        filters: [
            props.propertyFilters ? parsePropertyGroups(props.propertyFilters) : ({} as AndOrPropertyFilter),
            {
                setFilters: (_, { filters }) => filters,
                addFilterGroup: (state) => {
                    if (!state.values) {
                        return {
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [{}],
                                },
                            ],
                        }
                    }
                    const groupsCopy = clone(state)
                    groupsCopy.values.push({ type: FilterLogicalOperator.And, values: [{}] })

                    if (groupsCopy.values.length > 1 && !groupsCopy.type) {
                        groupsCopy.type = FilterLogicalOperator.And
                    }
                    return groupsCopy
                },
                removeFilterGroup: (state, { filterGroup }) => {
                    const newState = clone(state)
                    const removedFilterGroupState = {
                        ...newState,
                        values: newState.values.filter((_, idx: number) => idx !== filterGroup),
                    }
                    if (removedFilterGroupState.values.length <= 1) {
                        return { values: removedFilterGroupState.values }
                    }
                    return removedFilterGroupState
                },
                setPropertyGroupsType: (state, { type }) => {
                    return { ...state, type }
                },
                setPropertyFilters: (state, { properties, index }) => {
                    const newState = clone(state)
                    newState.values[index].values = properties
                    // removes entire property group if no properties in values
                    if (newState.values[index].values.length === 0) {
                        newState.values = newState.values.filter((_, i: number) => i !== index)
                    }
                    return newState
                },
                setPropertyGroupType: (state, { type, index }) => {
                    const newState = { ...state }
                    newState.values[index].type = type
                    return newState
                },
            },
        ],
    }),
    listeners: ({ actions, props, values }) => ({
        setFilters: () => actions.update(),
        setPropertyFilters: () => actions.update(),
        setPropertyGroupType: () => actions.update(),
        setPropertyGroupsType: () => actions.update(),
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
