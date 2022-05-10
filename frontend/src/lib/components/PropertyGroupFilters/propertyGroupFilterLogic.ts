import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'

import { PropertyGroupFilter, FilterLogicalOperator } from '~/types'
import { PropertyGroupFilterLogicProps } from 'lib/components/PropertyFilters/types'

import { propertyGroupFilterLogicType } from './propertyGroupFilterLogicType'
import { convertPropertiesToPropertyGroup, objectsEqual } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export const propertyGroupFilterLogic = kea<propertyGroupFilterLogicType>([
    path(['lib', 'components', 'PropertyGroupFilters', 'propertyGroupFilterLogic']),
    props({} as PropertyGroupFilterLogicProps),
    key((props) => props.pageKey),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.value && !objectsEqual(props.value, oldProps.value)) {
            actions.setFilters(props.value)
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
            convertPropertiesToPropertyGroup(props.value),
            {
                setFilters: (_, { filters }) => filters,
                addFilterGroup: (state) => {
                    if (!state.values) {
                        return {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [{}],
                                },
                            ],
                        }
                    }
                    const filterGroups = [...state.values, { type: FilterLogicalOperator.And, values: [{}] }]

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
        removeFilterGroup: () => actions.update(),
        addFilterGroup: () => {
            eventUsageLogic.actions.reportPropertyGroupFilterAdded()
            actions.update()
        },
        update: () => {
            props.onChange(values.filters)
        },
    })),

    selectors({
        propertyGroupFilter: [(s) => [s.filters], (propertyGroupFilter) => propertyGroupFilter],
    }),
])
