import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import { router } from 'kea-router'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { propertyFilterLogicType } from './propertyFilterLogicType'
import { AnyPropertyFilter, EmptyPropertyFilter, PropertyFilter, PropertyFilterValue, PropertyOperator } from '~/types'

export function parseProperties(
    input: AnyPropertyFilter[] | Record<string, string> | null | undefined
): AnyPropertyFilter[] {
    if (Array.isArray(input) || !input) {
        return input || []
    }
    // Old style dict properties
    return Object.entries(input).map(([inputKey, value]) => {
        const [key, operator] = inputKey.split('__')
        return {
            key,
            value,
            operator: operator as PropertyOperator,
            type: 'event',
        }
    })
}

export const propertyFilterLogic = kea<propertyFilterLogicType>({
    props: {} as {
        pageKey: string
        propertyFilters?: AnyPropertyFilter[] | null
        onChange?: null | ((filters: AnyPropertyFilter[]) => void)
    },
    key: (props) => props.pageKey,

    actions: () => ({
        update: true,
        setFilter: (
            index: number,
            key: PropertyFilter['key'],
            value: PropertyFilterValue,
            operator: PropertyFilter['operator'],
            type: PropertyFilter['type']
        ) => ({ index, key, value, operator, type }),
        setFilters: (filters: AnyPropertyFilter[]) => ({ filters }),
        newFilter: true,
        remove: (index: number) => ({ index }),
    }),

    reducers: ({ props }) => ({
        filters: [
            (props.propertyFilters ? parseProperties(props.propertyFilters) : []) as (
                | PropertyFilter
                | EmptyPropertyFilter
            )[],
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
            const cleanedFilters = [...values.filters].filter((property) => 'key' in property) as PropertyFilter[]

            // If the last item has a key, we need to add a new empty filter so the button appears
            if ('key' in values.filters[values.filters.length - 1]) {
                actions.newFilter()
            }
            if (props.onChange) {
                if (cleanedFilters.length === 0) {
                    return props.onChange([])
                }
                props.onChange(cleanedFilters)
            } else {
                const { properties, ...searchParams } = router.values.searchParams // eslint-disable-line
                const { pathname } = router.values.location

                searchParams.properties = cleanedFilters

                if (!objectsEqual(properties, cleanedFilters)) {
                    router.actions.push(pathname, searchParams)
                }
            }
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        '*': (_: Record<string, string>, { properties }: Record<string, any>) => {
            if (props.onChange) {
                return
            }

            let filters
            try {
                filters = values.filters
            } catch (error) {
                // since this is a catch-all route, this code might run during or after the logic was unmounted
                // if we have an error accessing the filter value, the logic is gone and we should return
                return
            }
            properties = parseProperties(properties)

            if (!objectsEqual(properties || {}, filters)) {
                // {} adds an empty row, which shows 'New Filter'
                actions.setFilters(properties ? [...properties, {}] : [{}])
            }
        },
    }),

    selectors: {
        filtersLoading: [() => [propertyDefinitionsModel.selectors.loaded], (loaded) => !loaded],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            actions.newFilter()
        },
    }),
})
