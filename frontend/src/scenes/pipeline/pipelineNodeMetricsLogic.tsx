import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { toParams } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'

import type { pipelineNodeMetricsLogicType } from './pipelineNodeMetricsLogicType'

export interface PipelineNodeMetricsProps {
    id: number | string // PluginConfig ID or batch export destination ID
}
const DEFAULT_DATE_FROM = '-7d'

export interface AppMetricsData {
    dates: Array<string>
    successes: Array<number>
    successes_on_retry: Array<number>
    failures: Array<number>
    totals: {
        successes: number
        successes_on_retry: number
        failures: number
    }
}
export interface AppMetricsResponse {
    metrics: AppMetricsData
    errors: Array<AppErrorSummary>
}
export interface AppErrorSummary {
    error_type: string
    count: number
    last_seen: string
}

export interface AppMetricErrorDetail {
    timestamp: string
    error_uuid: string
    error_type: string
    error_details: {
        error: {
            name: string
            message?: string
            stack?: string
        }
        event?: any
        eventCount?: number
    }
}

export const pipelineNodeMetricsLogic = kea<pipelineNodeMetricsLogicType>([
    props({} as PipelineNodeMetricsProps),
    key(({ id }: PipelineNodeMetricsProps) => id),
    path((id) => ['scenes', 'pipeline', 'appMetricsLogic', id]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        setDateRange: (from: string | null, to: string | null) => ({ from, to }),
        openErrorDetailsModal: (errorType: string) => ({
            errorType,
        }),
        closeErrorDetailsModal: true,
    }),
    loaders(({ values, props }) => ({
        appMetricsResponse: [
            null as AppMetricsResponse | null,
            {
                loadMetrics: async () => {
                    const params = toParams({ date_from: values.dateRange.from, date_to: values.dateRange.to })
                    return await api.get(`api/projects/${values.currentProjectId}/app_metrics/${props.id}?${params}`)
                },
            },
        ],
        errorDetails: [
            [] as Array<AppMetricErrorDetail>,
            {
                openErrorDetailsModal: async ({ errorType }) => {
                    const params = toParams({ error_type: errorType })
                    const { result } = await api.get(
                        `api/projects/${values.currentProjectId}/app_metrics/${props.id}/error_details?${params}`
                    )
                    return result
                },
            },
        ],
    })),
    reducers({
        dateRange: [
            { from: DEFAULT_DATE_FROM, to: null } as { from: string; to: string | null },
            {
                setDateRange: (_, { from, to }) => ({ from: from ?? DEFAULT_DATE_FROM, to: to }),
            },
        ],
        errorDetailsModalError: [
            null as string | null,
            {
                openErrorDetailsModal: (_, { errorType }) => errorType,
                closeErrorDetailsModal: () => null,
            },
        ],
    }),
    listeners(({ actions }) => ({
        setDateRange: () => {
            actions.loadMetrics()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadMetrics()
    }),
])
