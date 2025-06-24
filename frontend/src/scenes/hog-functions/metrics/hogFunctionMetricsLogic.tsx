import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { AppMetricsTotalsV2Response, AppMetricsV2RequestParams, AppMetricsV2Response } from '~/types'

import type { hogFunctionMetricsLogicType } from './hogFunctionMetricsLogicType'

export type HogFunctionMetricsLogicProps = {
    id: string
}

export type MetricsFilters = Pick<AppMetricsV2RequestParams, 'before' | 'after' | 'interval' | 'name'>

export const ALL_METRIC_TYPES = [
    { label: 'Succeeded', value: 'succeeded' },
    { label: 'Failed', value: 'failed' },
    { label: 'Filtered', value: 'filtered' },
    { label: 'Disabled temporarily', value: 'disabled_temporarily' },
    { label: 'Disabled permanently', value: 'disabled_permanently' },
    { label: 'Masked', value: 'masked' },
    { label: 'Filtering failed', value: 'filtering_failed' },
    { label: 'Inputs failed', value: 'inputs_failed' },
    { label: 'Fetch', value: 'fetch' },
]

const DEFAULT_FILTERS: MetricsFilters = {
    before: undefined,
    after: '-7d',
    interval: 'day',
    name: ALL_METRIC_TYPES.filter(({ value }) => value !== 'filtered')
        .map(({ value }) => value)
        .join(','),
}

export const hogFunctionMetricsLogic = kea<hogFunctionMetricsLogicType>([
    props({} as HogFunctionMetricsLogicProps),
    key(({ id }: HogFunctionMetricsLogicProps) => id),
    path((id) => ['scenes', 'pipeline', 'appMetricsLogic', id]),
    actions({
        setFilters: (filters: Partial<MetricsFilters>) => ({ filters }),
    }),
    loaders(({ values, props }) => ({
        appMetrics: [
            null as AppMetricsV2Response | null,
            {
                loadMetrics: async () => {
                    const params: AppMetricsV2RequestParams = {
                        ...values.filters,
                        breakdown_by: 'name',
                    }
                    try {
                        const result = await api.hogFunctions.metrics(props.id, params)
                        // Clear the series if no filters have been selected
                        if (values.filters.name === '') {
                            result.series = []
                        }
                        return result
                    } catch (e) {
                        // We don't want to be noisy here
                        return null
                    }
                },
            },
        ],

        appMetricsTotals: [
            null as AppMetricsTotalsV2Response | null,
            {
                loadMetricsTotals: async () => {
                    const params: AppMetricsV2RequestParams = {
                        ...values.filters,
                        breakdown_by: 'name',
                    }
                    delete params.name
                    return await api.hogFunctions.metricsTotals(props.id, params)
                },
            },
        ],
    })),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),
    listeners(({ actions }) => ({
        setFilters: async (_, breakpoint) => {
            await breakpoint(100)
            actions.loadMetrics()
            actions.loadMetricsTotals()
        },
    })),
])
