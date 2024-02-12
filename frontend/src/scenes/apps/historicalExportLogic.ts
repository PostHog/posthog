import { events, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { teamLogic } from '../teamLogic'
import { AppErrorSummary, AppMetrics, HistoricalExportInfo } from './appMetricsSceneLogic'
import type { historicalExportLogicType } from './historicalExportLogicType'

export interface HistoricalExportLogicProps {
    pluginConfigId: number
    jobId: string
}

export interface ExportData {
    metrics: AppMetrics
    summary: HistoricalExportInfo
    errors: Array<AppErrorSummary>
}

export const historicalExportLogic = kea<historicalExportLogicType>([
    path(['scenes', 'apps', 'historicalExportLogic']),
    props({} as HistoricalExportLogicProps),
    key(({ pluginConfigId, jobId }) => `${pluginConfigId}_${jobId}`),
    loaders(({ props }) => ({
        data: [
            null as ExportData | null,
            {
                loadExportData: async () => {
                    return await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/app_metrics/${props.pluginConfigId}/historical_exports/${props.jobId}`
                    )
                },
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: actions.loadExportData,
    })),
])
