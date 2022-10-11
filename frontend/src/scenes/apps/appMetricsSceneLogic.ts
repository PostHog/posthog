import { kea, key, props, path, actions, selectors, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import type { appMetricsSceneLogicType } from './appMetricsSceneLogicType'
import { urls } from 'scenes/urls'
import { Breadcrumb, PluginConfigWithPluginInfo } from '~/types'
import api from '../../lib/api'
import { teamLogic } from '../teamLogic'
import { actionToUrl, urlToAction } from 'kea-router'

export interface AppMetricsLogicProps {
    /** Used as the logic's key */
    pluginConfigId: number
}

export enum AppMetricsTab {
    Metrics = 'metrics',
    HistoricalExports = 'historical_exports',
}

export interface HistoricalExportInfo {
    job_id: string
    status: 'success' | 'fail' | 'not_finished'
    payload: Record<string, any>
    started_at: string
    finished_at?: string
    duration?: number
}

export const appMetricsSceneLogic = kea<appMetricsSceneLogicType>([
    path(['scenes', 'apps', 'appMetricsSceneLogic']),
    props({} as AppMetricsLogicProps),
    key((props) => props.pluginConfigId),

    actions({
        setActiveTab: (tab: AppMetricsTab) => ({ tab }),
        setOpenExportSections: (sections: Array<HistoricalExportInfo['job_id']>) => ({ sections }),
    }),

    reducers({
        activeTab: [
            AppMetricsTab.Metrics as AppMetricsTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],

        openExportSections: [
            [] as Array<HistoricalExportInfo['job_id']>,
            {
                setOpenExportSections: (_, { sections }) => sections,
            },
        ],
    }),

    loaders(({ props }) => ({
        pluginConfig: [
            null as PluginConfigWithPluginInfo | null,
            {
                loadPluginConfig: async () => {
                    return await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/plugin_configs/${props.pluginConfigId}`
                    )
                },
            },
        ],
        historicalExports: [
            [] as Array<HistoricalExportInfo>,
            {
                loadHistoricalExports: async () => {
                    const { results } = await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/app_metrics/${props.pluginConfigId}/historical_exports`
                    )
                    return results as Array<HistoricalExportInfo>
                },
            },
        ],
    })),

    selectors(() => ({
        breadcrumbs: [
            (s) => [s.pluginConfig, (_, props) => props.pluginConfigId],
            (pluginConfig, pluginConfigId: number): Breadcrumb[] => [
                {
                    name: 'Apps',
                    path: urls.projectApps(),
                },
                {
                    name: pluginConfig?.plugin_info?.name,
                    path: urls.appMetrics(pluginConfigId),
                },
            ],
        ],
    })),

    actionToUrl(({ values, props }) => ({
        setActiveTab: () => `/app/${props.pluginConfigId}/${values.activeTab}`,
    })),

    urlToAction(({ values, actions }) => ({
        '/app/:pluginConfigId/:tab': (params: Record<string, string | undefined>) => {
            actions.setActiveTab(params.tab as AppMetricsTab)
            if (!values.pluginConfig) {
                actions.loadPluginConfig()
            }
            if (params.tab === AppMetricsTab.HistoricalExports) {
                actions.loadHistoricalExports()
            }
        },
    })),
])
