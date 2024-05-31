import { actions, kea, key, path, props, propsChanged, reducers } from 'kea'
import { objectsEqual } from 'lib/utils'

import { EmptyPropertyFilter, FilterLogicalOperator } from '~/types'

import { UniversalGroupFilterValue } from './UniversalFilters'
import type { universalFiltersLogicType } from './universalFiltersLogicType'

const DEFAULT_UNIVERSAL_GROUP_FILTER = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [{} as EmptyPropertyFilter],
        },
    ],
}

export type UniversalFiltersLogicProps = {
    pageKey: string
    filters: UniversalGroupFilterValue | null
}

export const universalFiltersLogic = kea<universalFiltersLogicType>([
    path((key) => ['lib', 'components', 'UniversalFilters', 'universalFiltersLogic', key]),
    props({} as UniversalFiltersLogicProps),
    key((props) => props.pageKey),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.filters && !objectsEqual(props.filters, oldProps.filters)) {
            actions.setFilters(props.filters)
        }
    }),

    actions({
        addFilterGroup: true,
        setFilters: (filters: UniversalGroupFilterValue) => ({ filters }),
        removeFilterGroup: (filterGroup: number) => ({ filterGroup }),
        setOuterGroupsType: (type: FilterLogicalOperator) => ({ type }),
        setInnerGroupFilters: (filters, index: number) => ({ filters, index }),
        setInnerGroupType: (type: FilterLogicalOperator, index: number) => ({ type, index }),
    }),

    reducers(({ props }) => ({
        rootGroup: [
            props.filters || DEFAULT_UNIVERSAL_GROUP_FILTER,
            {
                setFilters: (_, { filters }) => filters,
                addFilterGroup: (state) => {
                    const filterGroups = [
                        ...state.values,
                        { type: FilterLogicalOperator.And, values: [{} as EmptyPropertyFilter] },
                    ]

                    return { ...state, values: filterGroups }
                },
                removeFilterGroup: (state, { filterGroup }) => {
                    const filteredGroups = [...state.values]
                    filteredGroups.splice(filterGroup, 1)
                    return { ...state, values: filteredGroups }
                },
                setOuterGroupsType: (state, { type }) => {
                    return { ...state, type }
                },
                setInnerGroupFilters: (state, { filters, index }) => {
                    const values = [...state.values]
                    values[index] = { ...values[index], values: filters }

                    return { ...state, values }
                },
                setInnerGroupType: (state, { type, index }) => {
                    const values = [...state.values]
                    values[index] = { ...values[index], type }
                    return { ...state, values }
                },
            },
        ],
    })),
])
