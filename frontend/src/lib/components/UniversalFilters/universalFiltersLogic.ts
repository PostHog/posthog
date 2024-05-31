import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { getDefaultEventLabel, getDefaultEventName } from 'lib/utils/getAppContext'
import { taxonomicFilterGroupTypeToEntityType } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ActionFilter, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { createDefaultPropertyFilter, taxonomicFilterTypeToPropertyFilterType } from '../PropertyFilters/utils'
import { TaxonomicFilterGroup, TaxonomicFilterValue } from '../TaxonomicFilter/types'
import { UniversalFilterValue, UniversalGroupFilterGroup, UniversalGroupFilterValue } from './UniversalFilters'
import type { universalFiltersLogicType } from './universalFiltersLogicType'

const DEFAULT_UNIVERSAL_GROUP_FILTER: UniversalGroupFilterGroup = {
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
    group: UniversalGroupFilterGroup | null
    onChange: (group: UniversalGroupFilterGroup) => void
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
        setGroupValues: (newValues: UniversalGroupFilterValue[]) => ({ newValues }),
        replaceGroupValue: (index: number, value: AnyPropertyFilter | ActionFilter | UniversalGroupFilterValue) => ({
            index,
            value,
        }),
        removeGroupValue: (index: number) => ({ index }),

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
                replaceGroupValue: (state, { index, value }) => {
                    const newValues = [...state.values]
                    newValues.splice(index, 1, value)
                    return { ...state, values: newValues }
                },
                removeGroupValue: (state, { index }) => {
                    const newValues = [...state.values]
                    newValues.splice(index, 1)
                    return { ...state, values: newValues }
                },
            },
        ],
    })),

    listeners(({ props, values, actions }) => ({
        setGroupType: () => props.onChange(values.filterGroup),
        setGroupValues: () => props.onChange(values.filterGroup),
        replaceGroupValue: () => props.onChange(values.filterGroup),
        removeGroupValue: () => props.onChange(values.filterGroup),

        addGroupFilter: ({ taxonomicGroup, propertyKey, itemPropertyFilterType }) => {
            const newValues = [...values.filterGroup.values]

            const propertyType = itemPropertyFilterType ?? taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type)
            if (propertyKey && propertyType) {
                const newPropertyFilter = createDefaultPropertyFilter(
                    {},
                    propertyKey,
                    propertyType,
                    taxonomicGroup,
                    values.describeProperty
                )

                newValues.push(newPropertyFilter)
            } else {
                const entityType = itemPropertyFilterType ?? taxonomicFilterGroupTypeToEntityType(taxonomicGroup.type)
                if (entityType) {
                    const newEntityFilter: ActionFilter = {
                        id: getDefaultEventName(),
                        name: getDefaultEventLabel(),
                        type: entityType,
                    }

                    newValues.push(newEntityFilter)
                }
            }
            actions.setGroupValues(newValues)
        },
    })),
])
