import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { AppMetricsTotalsV2Response, AppMetricsV2RequestParams, AppMetricsV2Response } from '~/types'

import type { appMetricsV2LogicType } from './appMetricsV2LogicType'

export type AppMetricsV2LogicProps = {
    id: string
}

export type MetricsFilters = Pick<AppMetricsV2RequestParams, 'before' | 'after' | 'interval'>

const DEFAULT_FILTERS: MetricsFilters = {
    before: undefined,
    after: '-7d',
    interval: 'day',
}

export const appMetricsV2Logic = kea<appMetricsV2LogicType>([
    props({} as AppMetricsV2LogicProps),
    key(({ id }: AppMetricsV2LogicProps) => id),
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
                    return await api.hogFunctions.metrics(props.id, params)
                },
            },
        ],

        appMetricsTotals: [
            null as AppMetricsTotalsV2Response | null,
            {
                loadMetricsTotals: async () => {
                    const params: AppMetricsV2RequestParams = {
                        breakdown_by: 'name',
                    }
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
        },
    })),
])
