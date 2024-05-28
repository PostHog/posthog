import { actions, kea, path, props, reducers, selectors } from 'kea'

import { FilterLogicalOperator, PropertyGroupFilterValue } from '~/types'

import type { hogQLFilterLogicType } from './hogQLFilterLogicType'

export interface HogQLRecordingFilters {
    /**
     * live mode is front end only, sets date_from and date_to to the last hour
     */
    live_mode?: boolean
    date_from?: string | null
    date_to?: string | null
    filter_test_accounts?: boolean
    filterGroups: PropertyGroupFilterValue
}

export type HogQLFilterLogicProps = {
    filters: HogQLRecordingFilters
    setFilters: (filters: HogQLRecordingFilters) => void
}

export const hogQLFilterLogic = kea<hogQLFilterLogicType>([
    path(['sessionRecordings', 'filters', 'hogQLFilterLogic']),
    props({} as HogQLFilterLogicProps),
    // key((props) => props.pageKey),
    actions({
        //     update: (propertyGroupIndex?: number) => ({ propertyGroupIndex }),
        //     setFilters: (filters: PropertyGroupFilter) => ({ filters }),
        //     removeFilterGroup: (filterGroup: number) => ({ filterGroup }),
        setOuterPropertyGroupsType: (type: FilterLogicalOperator) => ({ type }),
        //     setPropertyFilters: (properties, index: number) => ({ properties, index }),
        setInnerPropertyGroupType: (type: FilterLogicalOperator, index: number) => ({ type, index }),
        //     duplicateFilterGroup: (propertyGroupIndex: number) => ({ propertyGroupIndex }),
        //     addFilterGroup: true,
    }),
    reducers(({ props }) => ({
        filters: [
            props.filters,
            {
                setFilters: (_, { filters }) => filters,
                //             addFilterGroup: (state) => {
                //                 if (!state.values) {
                //                     return {
                //                         type: FilterLogicalOperator.And,
                //                         values: [
                //                             {
                //                                 type: FilterLogicalOperator.And,
                //                                 values: [{} as EmptyPropertyFilter],
                //                             },
                //                         ],
                //                     }
                //                 }
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
                setOuterPropertyGroupsType: (state, { type }) => {
                    return { ...state, type }
                },
                //             setPropertyFilters: (state, { properties, index }) => {
                //                 const values = [...state.values]
                //                 values[index] = { ...values[index], values: properties }
                //                 return { ...state, values }
                //             },
                setInnerPropertyGroupType: (state, { type, index }) => {
                    const values = [...state.values]
                    values[index] = { ...values[index], type }
                    return { ...state, values }
                },
                //             duplicateFilterGroup: (state, { propertyGroupIndex }) => {
                //                 const values = state.values.concat([state.values[propertyGroupIndex]])
                //                 return { ...state, values }
                //             },
            },
        ],
    })),
    // listeners(({ actions, props, values }) => ({
    //     setFilters: () => actions.update(),
    //     setPropertyFilters: () => actions.update(),
    //     setInnerPropertyGroupType: ({ type, index }) => {
    //         eventUsageLogic.actions.reportChangeInnerPropertyGroupFiltersType(
    //             type,
    //             values.filters.values[index].values.length
    //         )
    //         actions.update()
    //     },
    //     setOuterPropertyGroupsType: ({ type }) => {
    //         eventUsageLogic.actions.reportChangeOuterPropertyGroupFiltersType(type, values.filters.values.length)
    //         actions.update()
    //     },
    //     removeFilterGroup: () => actions.update(),
    //     addFilterGroup: () => {
    //         eventUsageLogic.actions.reportPropertyGroupFilterAdded()
    //     },
    //     update: () => {
    //         props.setQuery({ ...props.query, properties: values.filters })
    //     },
    // })),
    // selectors({
    //     propertyGroupFilter: [(s) => [s.filters], (propertyGroupFilter) => propertyGroupFilter],
    // }),
    selectors({
        rootFilter: [(s) => [s.filters], (rootFilter) => rootFilter],
    }),
])
