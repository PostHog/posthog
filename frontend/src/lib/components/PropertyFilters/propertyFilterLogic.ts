import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { propertyFilterLogicType } from './propertyFilterLogicType'
import {
    AnyPropertyFilter,
    EmptyPropertyFilter,
    EventPropertyFilter,
    FilterOperatorCache,
    GroupPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
} from '~/types'
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
        setFilterInner: (index: number, property: AnyPropertyFilter) => ({ index, property }),
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
                setFilterInner: (state, { index, property }) => {
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
                remove: (state, { index }) => {
                    const newState = state.filter((_: AnyPropertyFilter, i: number) => i !== index)
                    if (newState.length === 0) {
                        return []
                    }
                    return parsePropertiesForFiltersCache(newState)
                },
                setFilterCaches: (state, { index, operator, property }) => {
                    const newFiltersCache: FilterOperatorCache[] = [...state]
                    const cachedFilterKey = newFiltersCache[index]?.[operator]?.key
                    if (!cachedFilterKey || cachedFilterKey === property.key) {
                        newFiltersCache[index] = { ...newFiltersCache[index], [operator]: property }
                        return newFiltersCache
                    }
                    return parsePropertiesForFiltersCache(props.propertyFilters)
                },
            },
        ],
    })),

    listeners(({ actions, props, values }) => ({
        // Only send update if value is set to something
        setFilter: ({ index, property }) => {
            const operator = (property as EventPropertyFilter | PersonPropertyFilter | GroupPropertyFilter)?.operator
            const cachedProperty = operator && values.filtersOperatorsCache?.[index]?.[operator]
            const storedFilterOperator = (
                values.filters[index] as EventPropertyFilter | PersonPropertyFilter | GroupPropertyFilter
            )?.operator
            actions.setFilterInner(
                index,
                cachedProperty?.value && operator !== storedFilterOperator ? cachedProperty : property
            )
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
