import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'

import { convertPropertiesToPropertyGroup, isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { objectsEqual } from 'lib/utils/objects'

import { ProductAnalyticsInsightQueryNode } from '~/queries/schema/schema-general'
import {
    AnyFilterLike,
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
} from '~/types'

import type { propertyGroupFilterLogicType } from './propertyGroupFilterLogicType'

export type PropertyGroupFilterLogicProps = {
    pageKey: string
    query: ProductAnalyticsInsightQueryNode
    setQuery: (node: ProductAnalyticsInsightQueryNode) => void
}

export const propertyGroupFilterLogic = kea<propertyGroupFilterLogicType>([
    path(['queries', 'nodes', 'InsightViz', 'PropertyGroupFilters', 'propertyGroupFilterLogic']),
    props({} as PropertyGroupFilterLogicProps),
    key((props) => props.pageKey),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.query && !objectsEqual(props.query.properties, oldProps.query.properties)) {
            actions.setFilters(convertPropertiesToPropertyGroup(props.query.properties))
        }
    }),

    actions({
        update: (propertyGroupIndex?: number) => ({ propertyGroupIndex }),
        setFilters: (filters: PropertyGroupFilter) => ({ filters }),
        removeFilterGroup: (filterGroup: number) => ({ filterGroup }),
        setOuterPropertyGroupsType: (type: FilterLogicalOperator) => ({ type }),
        setPropertyFilters: (properties, index: number) => ({ properties, index }),
        setInnerPropertyGroupType: (type: FilterLogicalOperator, index: number) => ({ type, index }),
        duplicateFilterGroup: (propertyGroupIndex: number) => ({ propertyGroupIndex }),
        addFilterGroup: true,
    }),

    reducers(({ props }) => ({
        filters: [
            convertPropertiesToPropertyGroup(props.query.properties),
            {
                setFilters: (_, { filters }) => filters,
                addFilterGroup: (state) => {
                    if (!state.values) {
                        return {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [],
                                },
                            ],
                        }
                    }
                    const filterGroups = [...state.values, { type: FilterLogicalOperator.And, values: [] }]

                    return { ...state, values: filterGroups }
                },
                removeFilterGroup: (state, { filterGroup }) => {
                    const filteredGroups = [...state.values]
                    filteredGroups.splice(filterGroup, 1)
                    return { ...state, values: filteredGroups }
                },
                setOuterPropertyGroupsType: (state, { type }) => {
                    return { ...state, type }
                },
                setPropertyFilters: (state, { properties, index }) => {
                    const values = [...state.values]
                    values[index] = { ...values[index], values: properties }

                    return { ...state, values }
                },
                setInnerPropertyGroupType: (state, { type, index }) => {
                    const values = [...state.values]
                    values[index] = { ...values[index], type }
                    return { ...state, values }
                },
                duplicateFilterGroup: (state, { propertyGroupIndex }) => {
                    const values = state.values.concat([state.values[propertyGroupIndex]])
                    return { ...state, values }
                },
            },
        ],
    })),
    listeners(({ actions, props, values }) => ({
        setFilters: () => actions.update(),
        setPropertyFilters: () => actions.update(),
        setInnerPropertyGroupType: ({ type, index }) => {
            eventUsageLogic.actions.reportChangeInnerPropertyGroupFiltersType(
                type,
                values.filters.values[index].values.length
            )
            actions.update()
        },
        setOuterPropertyGroupsType: ({ type }) => {
            eventUsageLogic.actions.reportChangeOuterPropertyGroupFiltersType(type, values.filters.values.length)
            actions.update()
        },
        removeFilterGroup: () => {
            eventUsageLogic.actions.reportPropertyGroupFilterRemoved()
            actions.update()
        },
        addFilterGroup: () => {
            eventUsageLogic.actions.reportPropertyGroupFilterAdded()
        },
        duplicateFilterGroup: () => {
            eventUsageLogic.actions.reportPropertyGroupFilterDuplicated()
        },
        update: () => {
            // Don't persist empty filter groups — they cause ghost empty groups when merged
            // with dashboard filters on the backend, and can silently break insights.
            // Prune individual empty groups too, not just the all empty structure.
            const properties = pruneEmptyPropertyGroups(values.filters)
            props.setQuery({ ...props.query, properties })
        },
    })),

    selectors({
        propertyGroupFilter: [(s) => [s.filters], (propertyGroupFilter) => propertyGroupFilter],
    }),
])

function pruneEmptyPropertyGroups(filter: PropertyGroupFilter): PropertyGroupFilter | undefined {
    const values = filter.values.filter((group: PropertyGroupFilterValue) => hasAnyFiltersInGroup(group))
    return values.length ? { ...filter, values } : undefined
}

function hasAnyFiltersInGroup(group: PropertyGroupFilterValue): boolean {
    return group.values.some((v: AnyFilterLike | PropertyGroupFilterValue) =>
        'values' in v && Array.isArray((v as PropertyGroupFilterValue).values)
            ? hasAnyFiltersInGroup(v as PropertyGroupFilterValue)
            : isValidPropertyFilter(v as AnyPropertyFilter)
    )
}
