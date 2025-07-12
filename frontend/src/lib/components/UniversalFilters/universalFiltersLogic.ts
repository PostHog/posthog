import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import {
    createDefaultPropertyFilter,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { taxonomicFilterGroupTypeToEntityType } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    ActionFilter,
    FeaturePropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { TaxonomicFilterGroup, TaxonomicFilterGroupType, TaxonomicFilterValue } from '../TaxonomicFilter/types'
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
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
}

export const universalFiltersLogic = kea<universalFiltersLogicType>([
    path((key) => ['lib', 'components', 'UniversalFilters', 'universalFiltersLogic', key]),
    props({} as UniversalFiltersLogicProps),
    key((props) => {
        return `${props.rootKey}-${JSON.stringify(props.group)}`
    }),

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

        addGroupFilter: (
            taxonomicGroup: TaxonomicFilterGroup,
            propertyKey: TaxonomicFilterValue,
            item: { propertyFilterType?: PropertyFilterType; name?: string; key?: string },
            originalQuery?: string
        ) => ({
            taxonomicGroup,
            propertyKey,
            item,
            originalQuery,
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
        taxonomicGroupTypes: [(_, p) => [p.taxonomicGroupTypes], (types) => types],
        taxonomicPropertyFilterGroupTypes: [
            (_, p) => [p.taxonomicGroupTypes],
            (types) =>
                types.filter((t) =>
                    [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.EventFeatureFlags,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.Elements,
                        TaxonomicFilterGroupType.HogQLExpression,
                        TaxonomicFilterGroupType.FeatureFlags,
                        TaxonomicFilterGroupType.LogAttributes,
                    ].includes(t)
                ),
        ],
    }),

    listeners(({ props, values, actions }) => ({
        setGroupType: () => props.onChange(values.filterGroup),
        setGroupValues: () => props.onChange(values.filterGroup),
        replaceGroupValue: () => props.onChange(values.filterGroup),
        removeGroupValue: () => props.onChange(values.filterGroup),

        addGroupFilter: ({ taxonomicGroup, propertyKey, item, originalQuery }) => {
            const newValues = [...values.filterGroup.values]

            if (taxonomicGroup.type === TaxonomicFilterGroupType.FeatureFlags) {
                if (!item.key) {
                    return
                }
                const newFeatureFlagFilter: FeaturePropertyFilter = {
                    type: PropertyFilterType.Feature,
                    key: item.key,
                    operator: PropertyOperator.Exact,
                }
                newValues.push(newFeatureFlagFilter)
            } else {
                const propertyType =
                    item?.propertyFilterType ?? taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type)
                if (propertyKey && propertyType) {
                    const newPropertyFilter = createDefaultPropertyFilter(
                        {},
                        propertyKey,
                        propertyType,
                        taxonomicGroup,
                        values.describeProperty,
                        originalQuery
                    )
                    newValues.push(newPropertyFilter)
                } else {
                    const entityType = taxonomicFilterGroupTypeToEntityType(taxonomicGroup.type)
                    if (entityType) {
                        const newEntityFilter: ActionFilter = {
                            id: propertyKey,
                            name: item?.name ?? '',
                            type: entityType,
                        }

                        newValues.push(newEntityFilter)
                    }
                }
            }
            actions.setGroupValues(newValues)
        },
    })),
])
