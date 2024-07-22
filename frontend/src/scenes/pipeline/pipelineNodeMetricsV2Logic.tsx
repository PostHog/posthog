import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { AppMetricsV2RequestParams, AppMetricsV2Response } from '~/types'

import type { pipelineNodeMetricsV2LogicType } from './pipelineNodeMetricsV2LogicType'

export type PipelineNodeMetricsProps = {
    id: string
}

export type MetricsFilters = Pick<AppMetricsV2RequestParams, 'before' | 'after' | 'interval'>

const DEFAULT_FILTERS: MetricsFilters = {
    before: undefined,
    after: '-7d',
    interval: 'day',
}

export const pipelineNodeMetricsV2Logic = kea<pipelineNodeMetricsV2LogicType>([
    props({} as PipelineNodeMetricsProps),
    key(({ id }: PipelineNodeMetricsProps) => id),
    path((id) => ['scenes', 'pipeline', 'appMetricsLogic', id]),
    actions({
        setFilters: (filters: Partial<MetricsFilters>) => ({ filters }),
    }),
    loaders(({ values, props }) => ({
        appMetrics: [
            null as AppMetricsV2Response,
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
        setFilters: () => {
            actions.loadMetrics()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMetrics()
    }),
])
