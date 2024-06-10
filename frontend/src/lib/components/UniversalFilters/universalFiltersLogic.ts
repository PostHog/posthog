import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import {
    createDefaultPropertyFilter,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { taxonomicFilterGroupTypeToEntityType } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ActionFilter, FilterLogicalOperator } from '~/types'

import { TaxonomicFilterGroup, TaxonomicFilterGroupType, TaxonomicFilterValue } from '../TaxonomicFilter/types'
import { UniversalFiltersGroup, UniversalFiltersGroupValue } from './UniversalFilters'
import type { universalFiltersLogicType } from './universalFiltersLogicType'

export const DEFAULT_UNIVERSAL_GROUP_FILTER: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [],
        },
    ],
}

export type UniversalFiltersLogicProps = {
    rootKey: string
    group: UniversalFiltersGroup | null
    onChange: (group: UniversalFiltersGroup) => void
    taxonomicEntityFilterGroupTypes: TaxonomicFilterGroupType[]
    taxonomicPropertyFilterGroupTypes: TaxonomicFilterGroupType[]
}

export const universalFiltersLogic = kea<universalFiltersLogicType>([
    path((key) => ['lib', 'components', 'UniversalFilters', 'universalFiltersLogic', key]),
    props({} as UniversalFiltersLogicProps),
    key((props) => props.rootKey),

    connect(() => ({
        values: [propertyDefinitionsModel, ['describeProperty']],
    })),

    actions({
        addFilterGroup: true,

        setGroupType: (type: FilterLogicalOperator) => ({ type }),
        setGroupValues: (newValues: UniversalFiltersGroupValue[]) => ({ newValues }),
        replaceGroupValue: (index: number, value: UniversalFiltersGroupValue) => ({
            index,
            value,
        }),
        removeGroupValue: (index: number) => ({ index }),

        addGroupFilter: (taxonomicGroup: TaxonomicFilterGroup, propertyKey: TaxonomicFilterValue, item: any) => ({
            taxonomicGroup,
            propertyKey,
            item,
        }),
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

    selectors({
        rootKey: [(_, p) => [p.rootKey], (rootKey) => rootKey],
        taxonomicEntityFilterGroupTypes: [(_, p) => [p.taxonomicEntityFilterGroupTypes], (types) => types],
        taxonomicPropertyFilterGroupTypes: [(_, p) => [p.taxonomicPropertyFilterGroupTypes], (types) => types],
        taxonomicGroupTypes: [
            (_, p) => [p.taxonomicEntityFilterGroupTypes, p.taxonomicPropertyFilterGroupTypes],
            (entityTypes, propertyTypes) => [...entityTypes, ...propertyTypes],
        ],
    }),

    listeners(({ props, values, actions }) => ({
        setGroupType: () => props.onChange(values.filterGroup),
        setGroupValues: () => props.onChange(values.filterGroup),
        replaceGroupValue: () => props.onChange(values.filterGroup),
        removeGroupValue: () => props.onChange(values.filterGroup),

        addGroupFilter: ({ taxonomicGroup, propertyKey, item }) => {
            const newValues = [...values.filterGroup.values]

            const propertyType = item.propertyFilterType ?? taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type)
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
                const entityType = item.PropertyFilterType ?? taxonomicFilterGroupTypeToEntityType(taxonomicGroup.type)
                if (entityType) {
                    const newEntityFilter: ActionFilter = {
                        id: propertyKey,
                        name: item?.name ?? '',
                        type: entityType,
                    }

                    newValues.push(newEntityFilter)
                }
            }
            actions.setGroupValues(newValues)
        },
    })),
])
