import { kea } from 'kea'

import { AndOrPropertyFilter } from '~/types'
import { parsePropertyGroups } from 'lib/components/PropertyFilters/utils'
import { PropertyGroupFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { AndOr } from '../PropertyGroupFilters/PropertyGroupFilters'

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
        setPropertyGroupsType: (type: AndOr) => ({ type }),
        setPropertyFilters: (properties, index: number) => ({ properties, index }),
        setPropertyGroupType: (type: AndOr, index: number) => ({ type, index }),
        addFilterGroup: true,
    }),

    reducers: ({ props }) => ({
        filters: [
            props.propertyFilters ? parsePropertyGroups(props.propertyFilters) : ({} as AndOrPropertyFilter),
            {
                setFilters: (_, { filters }) => filters,
                addFilterGroup: (state) => {
                    if (!state.groups) {
                        return {
                            groups: [
                                {
                                    type: AndOr.AND,
                                    groups: [{}],
                                },
                            ],
                        }
                    }
                    const groupsCopy = clone(state)
                    groupsCopy.groups.push({ type: AndOr.AND, groups: [{}] })

                    if (groupsCopy.groups.length > 1 && !groupsCopy.type) {
                        groupsCopy.type = AndOr.AND
                    }
                    return groupsCopy
                },
                removeFilterGroup: (state, { filterGroup }) => {
                    const newState = clone(state)
                    const removedFilterGroupState = {
                        ...newState,
                        groups: newState.groups.filter((_, idx: number) => idx !== filterGroup),
                    }
                    if (removedFilterGroupState.groups.length <= 1) {
                        return { groups: removedFilterGroupState.groups }
                    }
                    return removedFilterGroupState
                },
                setPropertyGroupsType: (state, { type }) => {
                    return { ...state, type }
                },
                setPropertyFilters: (state, { properties, index }) => {
                    const newState = clone(state)
                    newState.groups[index].groups = properties
                    // removes entire property group if no properties in groups
                    if (newState.groups[index].groups.length === 0) {
                        newState.groups = newState.groups.filter((_, i: number) => i !== index)
                    }
                    return newState
                },
                setPropertyGroupType: (state, { type, index }) => {
                    const newState = { ...state }
                    newState.groups[index].type = type
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
