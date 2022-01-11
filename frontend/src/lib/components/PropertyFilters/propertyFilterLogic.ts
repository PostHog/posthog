import { kea } from 'kea'

import { propertyFilterLogicType } from './propertyFilterLogicType'
import { AnyPropertyFilter, PropertyFilter } from '~/types'
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
                setFilters: (_, { filters }) => parseProperties(filters),
                remove: (state, { index }) => state.filter((_, i) => i !== index),
            },
        ],
    }),

    selectors: {
        filterWithEmpty: [
            (s) => [s.filters],
            (filters) =>
                filters.length > 0
                    ? isValidPropertyFilter(filters[filters.length - 1])
                        ? [...filters, {}]
                        : filters
                    : [{}],
        ],
    },

    listeners: ({ actions, props, values }) => ({
        setFilter: ({ value }) => {
            // Only send update if value is set to something
            value && actions.update()
        },
        remove: () => {
            actions.update()
        },
        update: () => {
            props.onChange(values.filters)
        },
    }),
})
