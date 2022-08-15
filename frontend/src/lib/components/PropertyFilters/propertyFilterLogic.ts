import { kea } from 'kea'

import type { propertyFilterLogicType } from './propertyFilterLogicType'
import { AnyPropertyFilter, EmptyPropertyFilter, PropertyFilter } from '~/types'
import { isValidPropertyFilter, parseProperties } from 'lib/components/PropertyFilters/utils'
import { PropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'

export const propertyFilterLogic = kea<propertyFilterLogicType>({
    path: (key) => ['lib', 'components', 'PropertyFilters', 'propertyFilterLogic', key],
    props: {} as PropertyFilterLogicProps,
    key: (props) => props.pageKey,

    actions: () => ({
        update: true,
        setFilter: (
            index: number,
            key: PropertyFilter['key'],
            value: PropertyFilter['value'],
            operator: PropertyFilter['operator'],
            type: PropertyFilter['type'],
            group_type_index?: PropertyFilter['group_type_index']
        ) => ({ index, key, value, operator, type, group_type_index }),
        setFilters: (filters: AnyPropertyFilter[]) => ({ filters }),
        remove: (index: number) => ({ index }),
    }),

    reducers: ({ props }) => ({
        filters: [
            props.propertyFilters ? parseProperties(props.propertyFilters) : ([] as AnyPropertyFilter[]),
            {
                setFilter: (state, { index, ...property }) => {
                    const newFilters = [...state]
                    newFilters[index] = property
                    return newFilters
                },
                setFilters: (_, { filters }) => filters,
                remove: (state, { index }) => {
                    const newState = state.filter((_, i) => i !== index)
                    if (newState.length === 0) {
                        return [{} as EmptyPropertyFilter]
                    }
                    if (Object.keys(newState[newState.length - 1]).length !== 0) {
                        return [...newState, {}]
                    }
                    return newState
                },
            },
        ],
    }),

    listeners: ({ actions, props, values }) => ({
        // Only send update if value is set to something
        setFilter: ({ value }) => {
            value && actions.update()
        },
        remove: () => actions.update(),
        update: () => {
            const cleanedFilters = [...values.filters].filter(isValidPropertyFilter)

            props.onChange(cleanedFilters)
        },
    }),

    selectors: {
        filledFilters: [(s) => [s.filters], (filters) => filters.filter(isValidPropertyFilter)],
        filtersWithNew: [
            (s) => [s.filters],
            (filters) => {
                if (filters.length === 0 || isValidPropertyFilter(filters[filters.length - 1])) {
                    return [...filters, {}]
                } else {
                    return filters
                }
            },
        ],
    },
})
