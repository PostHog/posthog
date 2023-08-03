import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { propertyFilterLogicType } from './propertyFilterLogicType'
import { AnyPropertyFilter, EmptyPropertyFilter, FilterOperatorCache, PropertyOperator } from '~/types'
import {
    isValidPropertyFilter,
    parseProperties,
    parsePropertiesForFiltersCache,
} from 'lib/components/PropertyFilters/utils'
import { PropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'

export const propertyFilterLogic = kea<propertyFilterLogicType>([
    path((key) => ['lib', 'components', 'PropertyFilters', 'propertyFilterLogic', key]),
    props({} as PropertyFilterLogicProps),
    key((props) => props.pageKey),

    actions({
        update: true,
        setFilter: (index: number, property: AnyPropertyFilter) => ({ index, property }),
        setFilters: (filters: AnyPropertyFilter[]) => ({ filters }),
        remove: (index: number) => ({ index }),
        setFilterCaches: (index: number, operator: PropertyOperator, property: AnyPropertyFilter) => ({
            index,
            operator,
            property,
        }),
    }),

    reducers(({ props }) => ({
        filters: [
            props.propertyFilters ? parseProperties(props.propertyFilters) : ([] as AnyPropertyFilter[]),
            {
                setFilter: (state, { index, property }) => {
                    const newFilters: AnyPropertyFilter[] = [...state]
                    newFilters[index] = property
                    return newFilters
                },
                setFilters: (_, { filters }) => {
                    return filters
                },
                remove: (state, { index }) => {
                    const newState = state.filter((_, i) => i !== index)
                    if (newState.length === 0) {
                        return [{} as EmptyPropertyFilter]
                    }
                    if (Object.keys(newState[newState.length - 1]).length !== 0) {
                        return [...newState, {} as EmptyPropertyFilter]
                    }
                    return newState
                },
            },
        ],
        filtersOperatorsCache: [
            props.propertyFilters
                ? parsePropertiesForFiltersCache(props.propertyFilters)
                : ([] as FilterOperatorCache[]),
            {
                setFilter: (state, { index, property }) => {
                    const newFilters: FilterOperatorCache[] = [...state]
                    if (
                        property?.operator &&
                        newFilters?.[index]?.[property.operator] &&
                        newFilters[index][property.operator].key === property.key
                    ) {
                        newFilters[index] = { ...newFilters[index], [property.operator]: property }
                        return newFilters
                    }
                    newFilters[index] = { [property.operator]: property }
                    return newFilters
                },
                remove: (state, { index }) => {
                    const newState = state.filter((_: AnyPropertyFilter, i: number) => i !== index)
                    if (newState.length === 0) {
                        return []
                    }
                    return parsePropertiesForFiltersCache(newState)
                },
                setFilterCaches: (state, { index, operator, property }) => {
                    const newFilters: FilterOperatorCache[] = [...state]
                    newFilters[index] = { ...newFilters[index], [operator]: property }
                    return newFilters
                },
            },
        ],
    })),

    listeners(({ actions, props, values }) => ({
        // Only send update if value is set to something
        setFilter: ({ property }) => {
            if (props.sendAllKeyUpdates || property?.value || (property?.key && property.type === 'hogql')) {
                actions.update()
            }
        },
        remove: () => actions.update(),
        update: () => {
            const cleanedFilters = [...values.filters].filter(isValidPropertyFilter)
            props.onChange(cleanedFilters)
        },
    })),

    selectors({
        filledFilters: [(s) => [s.filters], (filters) => filters.filter(isValidPropertyFilter)],
        filtersWithNew: [
            (s) => [s.filters],
            (filters) => {
                if (filters.length === 0 || isValidPropertyFilter(filters[filters.length - 1])) {
                    return [...filters, {} as AnyPropertyFilter]
                } else {
                    return filters
                }
            },
        ],
    }),
])
