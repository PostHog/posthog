import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import type { pipelineNodeMetricsLogicType } from './pipelineNodeMetricsLogicType'

export interface PipelineNodeMetricsProps {
    pluginConfigId: number
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
    key(({ pluginConfigId }: PipelineNodeMetricsProps) => pluginConfigId),
    path((id) => ['scenes', 'pipeline', 'appMetricsLogic', id]),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
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
                    const params = toParams({ date_from: values.dateFrom })
                    return await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/app_metrics/${props.pluginConfigId}?${params}`
                    )
                },
            },
        ],
        errorDetails: [
            [] as Array<AppMetricErrorDetail>,
            {
                openErrorDetailsModal: async ({ errorType }) => {
                    const params = toParams({ error_type: errorType })
                    const { result } = await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/app_metrics/${props.pluginConfigId}/error_details?${params}`
                    )
                    return result
                },
            },
        ],
    })),
    reducers({
        dateFrom: [
            DEFAULT_DATE_FROM as string,
            {
                setDateFrom: (_, { dateFrom }) => dateFrom,
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
        setDateFrom: () => {
            actions.loadMetrics()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadMetrics()
    }),
])
