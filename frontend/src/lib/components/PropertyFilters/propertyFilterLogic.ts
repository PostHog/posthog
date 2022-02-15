import { kea } from 'kea'

import { propertyFilterLogicType } from './propertyFilterLogicType'
import { AnyPropertyFilter, AndOrPropertyFilter, EmptyPropertyFilter, PropertyFilter } from '~/types'
import { isValidPropertyFilter, parseProperties, parsePropertyGroups } from 'lib/components/PropertyFilters/utils'
import { PropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { AndOr } from '../MatchPropertyFilters/MatchPropertyFilters'

export function isAndOrPropertyFilter(
    filter: AndOrPropertyFilter | AnyPropertyFilter[]
): filter is AndOrPropertyFilter {
    return (<AndOrPropertyFilter>filter).groups !== undefined
}

export const propertyFilterLogic = kea<propertyFilterLogicType>({
    path: (key) => ['lib', 'components', 'PropertyFilters', 'propertyFilterLogic', key],
    props: {} as PropertyFilterLogicProps,
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
        setFilters: (filters: AnyPropertyFilter[]) => ({ filters }),
        remove: (propertyGroupIndex: number, propertyIndex?: number) => ({ propertyGroupIndex, propertyIndex }),
        addFilterGroup: true,
        addPropertyToGroup: (propertyGroupIndex) => ({ propertyGroupIndex }),
        removeFilterGroup: (filterGroup: number) => ({ filterGroup }),
    }),

    reducers: ({ props }) => ({
        filters: [
            props.propertyFilters
                ? isAndOrPropertyFilter(props.propertyFilters)
                    ? parsePropertyGroups(props.propertyFilters)
                    : parseProperties(props.propertyFilters)
                : ([] as AnyPropertyFilter[]),
            {
                setFilter: (state, { propertyGroupIndex, propertyIndex, index, ...property }) => {
                    if (isAndOrPropertyFilter(state)) {
                        if (propertyGroupIndex !== undefined && propertyIndex !== undefined) {
                            const newFilters = { ...state }
                            newFilters.groups[propertyGroupIndex].groups[propertyIndex] = property
                            return newFilters
                        }
                    } else {
                        const newFilters = [...state]
                        newFilters[index] = property
                        return newFilters
                    }
                },
                setFilters: (_, { filters }) => filters,
                remove: (state, { propertyGroupIndex, propertyIndex }) => {
                    if (isAndOrPropertyFilter(state)) {
                        if (propertyIndex !== undefined) {
                            const newGroupsState = { ...state }
                            newGroupsState.groups[propertyGroupIndex].groups = newGroupsState.groups[
                                propertyGroupIndex
                            ].groups.filter((_, idx) => idx !== propertyIndex)
                            if (newGroupsState.groups[propertyGroupIndex].groups.length === 0) {
                                // removes entire filter group if it contains no properties
                                newGroupsState.groups = newGroupsState.groups.filter(
                                    (_, i: number) => i !== propertyGroupIndex
                                )
                            }
                            return newGroupsState
                        }
                    } else {
                        const newState = state.filter((_, i) => i !== propertyGroupIndex)
                        if (newState.length === 0) {
                            return [{} as EmptyPropertyFilter]
                        }
                        if (Object.keys(newState[newState.length - 1]).length !== 0) {
                            return [...newState, {}]
                        }
                        return newState
                    }
                },
                addFilterGroup: (state: AndOrPropertyFilter) => {
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
                    return groupsCopy
                },
                addPropertyToGroup: (state: AndOrPropertyFilter, { propertyGroupIndex }) => {
                    const newState = { ...state }
                    newState.groups[propertyGroupIndex].groups.push({})
                    return newState
                },
                removeFilterGroup: (state: AndOrPropertyFilter, { filterGroup }) => {
                    return { ...state, groups: state.groups.filter((_, idx: number) => idx !== filterGroup) }
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
            if (isAndOrPropertyFilter(values.filters)) {
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
            } else {
                const cleanedFilters = [...values.filters].filter(isValidPropertyFilter)
                props.onChange(cleanedFilters)
            }
        },
        addPropertyToGroup: () => actions.update(),
    }),

    selectors: {
        filledFilters: [
            (s) => [s.filters],
            (filters) => (isAndOrPropertyFilter(filters) ? filters : filters.filter(isValidPropertyFilter)),
        ],
        filtersWithNew: [
            (s) => [s.filters],
            (filters) => {
                if (isAndOrPropertyFilter(filters)) {
                    if (filters.groups) {
                        return filters
                    }
                } else {
                    if (filters.length === 0 || isValidPropertyFilter(filters[filters.length - 1])) {
                        return [...filters, {}]
                    }
                    return filters
                }
            },
        ],
    },
})
