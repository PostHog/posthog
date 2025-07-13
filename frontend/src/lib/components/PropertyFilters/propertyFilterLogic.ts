import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { PropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { isValidPropertyFilter, parseProperties } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter, EmptyPropertyFilter } from '~/types'

import type { propertyFilterLogicType } from './propertyFilterLogicType'

export const propertyFilterLogic = kea<propertyFilterLogicType>([
    path((key) => ['lib', 'components', 'PropertyFilters', 'propertyFilterLogic', key]),
    props({} as PropertyFilterLogicProps),
    key((props) => props.pageKey),

    actions({
        update: true,
        setFilter: (index: number, property: AnyPropertyFilter) => ({ index, property }),
        setFilters: (filters: AnyPropertyFilter[]) => ({ filters }),
        remove: (index: number) => ({ index }),
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
                setFilters: (_, { filters }) => filters,
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
    })),

    listeners(({ actions, props, values }) => ({
        // Only send update if value is set to something
        setFilter: async ({ property }) => {
            if (
                props.sendAllKeyUpdates ||
                property?.value ||
                ('operator' in property &&
                    property?.operator &&
                    ['is_set', 'is_not_set'].includes(property?.operator)) ||
                (property?.key && property.type === 'hogql')
            ) {
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
                }
                return filters
            },
        ],
    }),
])
