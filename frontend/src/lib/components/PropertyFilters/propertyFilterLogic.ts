import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import { router } from 'kea-router'

import { propertyFilterLogicType } from './propertyFilterLogicType'
import { AnyPropertyFilter, EmptyPropertyFilter, PropertyFilter } from '~/types'
import { isValidPropertyFilter, parseProperties } from 'lib/components/PropertyFilters/utils'
import { PropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

export const propertyFilterLogic = kea<propertyFilterLogicType>({
    path: (key) => ['lib', 'components', 'PropertyFilters', 'propertyFilterLogic', key],
    props: {} as PropertyFilterLogicProps,
    connect: {
        values: [propertyDefinitionsModel, ['findPropertyDefinitionsByName']],
    },
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
        ) => ({ index, property: { key, value, operator, type, group_type_index } as PropertyFilter }),
        setFilters: (filters: AnyPropertyFilter[]) => ({ filters }),
        newFilter: true,
        remove: (index: number) => ({ index }),
    }),

    reducers: ({ props }) => ({
        rawFilters: [
            props.propertyFilters ? parseProperties(props.propertyFilters) : ([] as AnyPropertyFilter[]),
            {
                setFilter: (state, { index, property }): AnyPropertyFilter[] => {
                    const newFilters = [...state]
                    newFilters[index] = property
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
        setFilter: ({ property }) => {
            property.value && actions.update()
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
                const { [`${props.urlOverride || 'properties'}`]: properties, ...searchParams } =
                    router.values.searchParams // eslint-disable-line
                const { pathname } = router.values.location

                searchParams[props.urlOverride || 'properties'] = cleanedFilters

                if (!objectsEqual(properties, cleanedFilters)) {
                    router.actions.replace(pathname, searchParams)
                }
            }
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        '*': (_, { [`${props.urlOverride || 'properties'}`]: properties }) => {
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
        filledFilters: [(s) => [s.filters], (filters) => filters.filter(isValidPropertyFilter)],
        filters: [
            (s) => [s.rawFilters, s.findPropertyDefinitionsByName],
            (rawFilters, findPropertyDefinitionsByName) => {
                return rawFilters.map((rawFilter) => {
                    const processedFilter = { ...rawFilter }
                    if (rawFilter.key && !rawFilter.property_type) {
                        const propertyDefinition = findPropertyDefinitionsByName(rawFilter.key)
                        if (propertyDefinition?.property_type) {
                            processedFilter.property_type = propertyDefinition.property_type
                            processedFilter.property_type_format = propertyDefinition.property_type_format
                        }
                    }
                    return processedFilter
                })
            },
        ],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            actions.newFilter()
        },
    }),
})
