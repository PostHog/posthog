import { kea } from 'kea'

import { AndOrPropertyFilter, PropertyFilter } from '~/types'
import { isValidPropertyFilter, parsePropertyGroups } from 'lib/components/PropertyFilters/utils'
import { PropertyGroupFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { AndOr } from '../PropertyGroupFilters/PropertyGroupFilters'

import { propertyGroupFilterLogicType } from './propertyGroupFilterLogicType'

export const propertyGroupFilterLogic = kea<propertyGroupFilterLogicType>({
    path: (key) => ['lib', 'components', 'PropertyGroupFilters', 'propertyGroupFilterLogic', key],
    props: {} as PropertyGroupFilterLogicProps,
    key: (props) => props.pageKey,

    actions: () => ({
        update: (propertyGroupIndex?: number) => ({ propertyGroupIndex }),
        setFilter: (
            index: number,
            key: PropertyFilter['key'],
            value: PropertyFilter['value'],
            operator: PropertyFilter['operator'],
            type: PropertyFilter['type'],
            group_type_index?: PropertyFilter['group_type_index'],
            propertyGroupIndex?: number,
            propertyIndex?: number
        ) => ({ index, key, value, operator, type, group_type_index, propertyGroupIndex, propertyIndex }),
        setFilters: (filters: AndOrPropertyFilter) => ({ filters }),
        remove: (propertyGroupIndex: number, propertyIndex?: number) => ({ propertyGroupIndex, propertyIndex }),
        addFilterGroup: true,
        addPropertyToGroup: (propertyGroupIndex: number) => ({ propertyGroupIndex }),
        removeFilterGroup: (filterGroup: number) => ({ filterGroup }),
        setPropertyGroupType: (type: AndOr) => ({ type }),
        setPropertyFilters: (properties, index: number) => ({ properties, index }),
    }),

    reducers: ({ props }) => ({
        filters: [
            props.propertyFilters
                ? // isAndOrPropertyFilter(props.propertyFilters)
                  // ? parsePropertyGroups(props.propertyFilters)
                  // : parseProperties(props.propertyFilters)
                  parsePropertyGroups(props.propertyFilters)
                : ({} as AndOrPropertyFilter),
            {
                // setFilter: (state, { propertyGroupIndex, propertyIndex, index, ...property }) => {
                //     // if (isAndOrPropertyFilter(state)) {
                //     const newFilters = { ...state }
                //     if (propertyGroupIndex !== undefined && propertyIndex !== undefined) {
                //         newFilters.groups[propertyGroupIndex].groups[propertyIndex] = property
                //     }
                //     return newFilters
                // },
                setFilters: (_, { filters }) => filters,
                // remove: (state, { propertyGroupIndex, propertyIndex }) => {
                //     if (propertyIndex !== undefined) {
                //         const newGroupsState = { ...state }
                //         newGroupsState.groups[propertyGroupIndex].groups = newGroupsState.groups[
                //             propertyGroupIndex
                //         ].groups.filter((_, idx) => idx !== propertyIndex)
                //         if (newGroupsState.groups[propertyGroupIndex].groups.length === 0) {
                //             // removes entire filter group if it contains no properties
                //             newGroupsState.groups = newGroupsState.groups.filter(
                //                 (_, i: number) => i !== propertyGroupIndex
                //             )
                //         }
                //         return newGroupsState
                //     }
                // },
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
                    const groupsCopy = { ...state }
                    groupsCopy.groups.push({ type: AndOr.AND, groups: [{}] })
                    if (groupsCopy.groups.length > 1) {
                        groupsCopy.type = AndOr.AND
                    }
                    return groupsCopy
                },
                addPropertyToGroup: (state, { propertyGroupIndex }) => {
                    const newState = { ...state }
                    newState.groups[propertyGroupIndex].groups.push({})
                    return newState
                },
                removeFilterGroup: (state, { filterGroup }) => {
                    return { ...state, groups: state.groups.filter((_, idx: number) => idx !== filterGroup) }
                },
                setPropertyGroupType: (state, { type }) => {
                    return { ...state, type }
                },
                setPropertyFilters: (state, { properties, index }) => {
                    const newState = { ...state }
                    newState.groups[index].groups = properties
                    return newState
                },
            },
        ],
    }),
    listeners: ({ actions, props, values }) => ({
        // Only send update if value is set to something
        setFilter: ({ value, propertyGroupIndex }) => {
            value && actions.update(propertyGroupIndex)
        },
        remove: () => actions.update(),
        removeFilterGroup: () => actions.update(),
        update: ({ propertyGroupIndex }) => {
            if (propertyGroupIndex !== undefined) {
                const filtersCopy = { ...values.filters }
                filtersCopy.groups[propertyGroupIndex].groups =
                    filtersCopy.groups[propertyGroupIndex].groups.filter(isValidPropertyFilter)
                props.onChange(filtersCopy)
                return
            } else {
                props.onChange(values.filters)
                return
            }
        },
        addFilterGroup: () => actions.update(),
        addPropertyToGroup: () => actions.update(),
    }),

    selectors: {
        filledFilters: [(s) => [s.filters], (filters) => filters],
        filtersWithNew: [
            (s) => [s.filters],
            (filters) => {
                return filters
                //     if (filters.length === 0 || isValidPropertyFilter(filters[filters.length - 1])) {
                //         return [...filters, {}]
                //     }
            },
        ],
    },
})
