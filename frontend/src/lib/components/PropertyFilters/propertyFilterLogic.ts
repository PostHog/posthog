import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import isEqual from 'lodash.isequal'

import { PropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { isValidPropertyFilter, parseProperties } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter, EmptyPropertyFilter } from '~/types'

import type { propertyFilterLogicType } from './propertyFilterLogicType'

export interface FilterItem {
    _id: number
    filter: AnyPropertyFilter
}

export interface FiltersState {
    nextId: number
    items: FilterItem[]
}

function initFiltersState(filters: AnyPropertyFilter[]): FiltersState {
    return {
        nextId: filters.length,
        items: filters.map((filter, i) => ({ _id: i, filter })),
    }
}

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
        _filtersState: [
            initFiltersState(props.propertyFilters ? parseProperties(props.propertyFilters) : []),
            {
                setFilter: (
                    state: FiltersState,
                    { index, property }: { index: number; property: AnyPropertyFilter }
                ) => {
                    if (index < state.items.length) {
                        const newItems = [...state.items]
                        newItems[index] = { _id: state.items[index]._id, filter: property }
                        return { ...state, items: newItems }
                    }
                    // Appending beyond current length (filling the virtual empty slot)
                    const newItems = [...state.items, { _id: state.nextId, filter: property }]
                    return { nextId: state.nextId + 1, items: newItems }
                },
                setFilters: (state: FiltersState, { filters }: { filters: AnyPropertyFilter[] }) => {
                    const currentFilters = state.items.map((i) => i.filter)
                    if (isEqual(currentFilters, filters)) {
                        return state
                    }
                    let nextId = state.nextId
                    const items: FilterItem[] = filters.map((filter, i) => {
                        if (i < state.items.length) {
                            return { _id: state.items[i]._id, filter }
                        }
                        return { _id: nextId++, filter }
                    })
                    return { nextId, items }
                },
                remove: (state: FiltersState, { index }: { index: number }) => {
                    const newItems = state.items.filter((_, i) => i !== index)
                    let nextId = state.nextId
                    if (newItems.length === 0) {
                        return { nextId: nextId + 1, items: [{ _id: nextId, filter: {} as EmptyPropertyFilter }] }
                    }
                    if (Object.keys(newItems[newItems.length - 1].filter).length !== 0) {
                        return {
                            nextId: nextId + 1,
                            items: [...newItems, { _id: nextId, filter: {} as EmptyPropertyFilter }],
                        }
                    }
                    return { ...state, items: newItems }
                },
            },
        ],
    })),

    listeners(({ actions, props, values }) => ({
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
        filters: [
            (s) => [s._filtersState],
            (state: FiltersState): AnyPropertyFilter[] => state.items.map((i) => i.filter),
        ],
        filterIds: [(s) => [s._filtersState], (state: FiltersState): number[] => state.items.map((i) => i._id)],
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
        filterIdsWithNew: [
            (s) => [s.filterIds, s._filtersState, s.filtersWithNew],
            (filterIds: number[], state: FiltersState, filtersWithNew: AnyPropertyFilter[]): number[] => {
                if (filtersWithNew.length > filterIds.length) {
                    return [...filterIds, state.nextId]
                }
                return filterIds
            },
        ],
    }),
])
