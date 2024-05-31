import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { FilterLogicalOperator } from '~/types'

import { createDefaultPropertyFilter, taxonomicFilterTypeToPropertyFilterType } from '../PropertyFilters/utils'
import { TaxonomicFilterGroup, TaxonomicFilterValue } from '../TaxonomicFilter/types'
import { UniversalFilterGroup, UniversalFilterValue } from './UniversalFilters'
import type { universalFiltersLogicType } from './universalFiltersLogicType'

const DEFAULT_UNIVERSAL_GROUP_FILTER: UniversalFilterGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [],
        },
    ],
}

export type UniversalFiltersLogicProps = {
    pageKey: string
    group: UniversalFilterGroup | null
    onChange: (group: UniversalFilterGroup) => void
}

export const universalFiltersLogic = kea<universalFiltersLogicType>([
    path((key) => ['lib', 'components', 'UniversalFilters', 'universalFiltersLogic', key]),
    props({} as UniversalFiltersLogicProps),
    key((props) => props.pageKey),

    connect(() => ({
        values: [propertyDefinitionsModel, ['describeProperty']],
    })),

    actions({
        addFilterGroup: true,

        setGroupType: (type: FilterLogicalOperator) => ({ type }),
        setGroupValues: (newValues: UniversalFilterGroup['values']) => ({ newValues }),
        replaceGroupValue: (index: number, group: UniversalFilterGroup) => ({ index, group }),

        addGroupFilter: (
            taxonomicGroup: TaxonomicFilterGroup,
            propertyKey: TaxonomicFilterValue,
            itemPropertyFilterType: any
        ) => ({
            taxonomicGroup,
            propertyKey,
            itemPropertyFilterType,
        }),
        updateGroupFilter: (index: number, filter: UniversalFilterValue) => ({ index, filter }),
        removeGroupFilter: (index: number) => ({ index }),
    }),

    reducers(({ props }) => ({
        filterGroup: [
            props.group || DEFAULT_UNIVERSAL_GROUP_FILTER,
            {
                setGroupType: (state, { type }) => {
                    return { ...state, type }
                },
                setGroupValues: (state, { newValues }) => {
                    return { ...state, values: newValues }
                },
                replaceGroupValue: (state, { index, group }) => {
                    const newValues = [...state.values]
                    newValues.splice(index, 1, group)
                    return { ...state, values: newValues }
                },
            },
        ],
    })),

    // reducers(({ props }) => ({
    //     filterGroup: [
    //         props.group || DEFAULT_UNIVERSAL_GROUP_FILTER,
    //         {
    //             setFilters: (_, { filters }) => filters,
    //             addFilterGroup: (state) => {
    //                 const filterGroups = [
    //                     ...state.values,
    //                     { type: FilterLogicalOperator.And, values: [{} as EmptyPropertyFilter] },
    //                 ]

    //                 return { ...state, values: filterGroups }
    //             },
    //             removeFilterGroup: (state, { filterGroup }) => {
    //                 const filteredGroups = [...state.values]
    //                 filteredGroups.splice(filterGroup, 1)
    //                 return { ...state, values: filteredGroups }
    //             },
    //             setOuterGroupsType: (state, { type }) => {
    //                 return { ...state, type }
    //             },
    //             setInnerGroupFilters: (state, { filters, index }) => {
    //                 const values = [...state.values]
    //                 values[index] = { ...values[index], values: filters }

    //                 return { ...state, values }
    //             },
    //             setInnerGroupType: (state, { type, index }) => {
    //                 const values = [...state.values]
    //                 values[index] = { ...values[index], type }
    //                 return { ...state, values }
    //             },
    //         },
    //     ],
    // })),

    listeners(({ props, values, actions }) => ({
        setGroupType: () => props.onChange(values.filterGroup),
        setGroupValues: () => props.onChange(values.filterGroup),
        replaceGroupValue: () => props.onChange(values.filterGroup),

        addGroupFilter: ({ taxonomicGroup, propertyKey, itemPropertyFilterType }) => {
            const propertyType = itemPropertyFilterType ?? taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type)
            if (propertyKey && propertyType) {
                const value = createDefaultPropertyFilter(
                    {},
                    propertyKey,
                    propertyType,
                    taxonomicGroup,
                    values.describeProperty
                )

                const newValues = [...values.filterGroup.values]
                newValues.push(value)

                actions.setGroupValues(newValues)
            }
        },
    })),
])
