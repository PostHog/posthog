import { kea } from 'kea'

import { propertyFilterLogicType } from './propertyFilterLogicType'
import { AnyPropertyFilter, EmptyPropertyFilter, PropertyFilter } from '~/types'
import { isValidPropertyFilter, parseProperties } from 'lib/components/PropertyFilters/utils'
import { PropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'

export const propertyFilterLogic = kea<propertyFilterLogicType>({
    props: {} as PropertyFilterLogicProps,
    key: (props) => props.pageKey,

    actions: () => ({
        update: true,
        setFilter: (
            index: number,
            key: PropertyFilter['key'],
            value: PropertyFilter['value'],
            operator: PropertyFilter['operator'],
            type: PropertyFilter['type']
        ) => ({ index, key, value, operator, type }),
        setFilters: (filters: AnyPropertyFilter[]) => ({ filters }),
        newFilter: true,
        remove: (index: number) => ({ index }),
    }),

    reducers: ({ props }) => ({
        filters: [
            props.propertyFilters ? parseProperties(props.propertyFilters) : ([] as AnyPropertyFilter[]),
            {
                setFilter: (state, { index, key, value, operator, type }) => {
                    const newFilters = [...state]
                    newFilters[index] = { key, value, operator, type }
                    return newFilters
                },
                setFilters: (_, { filters }) => filters,
                newFilter: (state) => {
                    return [...state, {} as EmptyPropertyFilter]
                },
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

            // if the last filter is used, add an empty filter to get the "new filter" button
            if (isValidPropertyFilter(values.filters[values.filters.length - 1])) {
                actions.newFilter()
            }

            if (props.onChange) {
                props.onChange(cleanedFilters)
            } else {
                throw new Error('Still running propertFilterLogic without onChange from somewhere!')
            }
        },
    }),

    selectors: {
        filledFilters: [(s) => [s.filters], (filters) => filters.filter(isValidPropertyFilter)],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            actions.newFilter()
        },
    }),
})
