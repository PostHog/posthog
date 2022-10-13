import { kea, key, props, path, actions, selectors, reducers, listeners } from 'kea'
import { loaders } from 'kea-loaders'

import type { appMetricsSceneLogicType } from './appMetricsSceneLogicType'
import { urls } from 'scenes/urls'
import { Breadcrumb, PluginConfigWithPluginInfo, UserBasicType } from '~/types'
import api from 'lib/api'
import { teamLogic } from '../teamLogic'
import { actionToUrl, urlToAction } from 'kea-router'
import { toParams } from 'lib/utils'

export interface AppMetricsLogicProps {
    /** Used as the logic's key */
    pluginConfigId: number
}

export enum AppMetricsTab {
    ProcessEvent = 'processEvent',
    OnEvent = 'onEvent',
    ExportEvents = 'exportEvents',
    HistoricalExports = 'historical_exports',
}

export interface HistoricalExportInfo {
    job_id: string
    status: 'success' | 'fail' | 'not_finished'
    payload: Record<string, any>
    created_at: string
    created_by: UserBasicType | null
    finished_at?: string
    duration?: number
}

export interface AppMetrics {
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

export interface AppErrorSummary {
    error_type: string
    count: number
    last_seen: string
}

export interface AppMetricsResponse {
    metrics: AppMetrics
    errors: Array<AppErrorSummary>
}

const INITIAL_TABS: Array<AppMetricsTab> = [
    AppMetricsTab.ProcessEvent,
    AppMetricsTab.OnEvent,
    AppMetricsTab.ExportEvents,
]

export const appMetricsSceneLogic = kea<appMetricsSceneLogicType>([
    path((key) => ['scenes', 'apps', 'appMetricsSceneLogic', key]),
    props({} as AppMetricsLogicProps),
    key((props) => props.pluginConfigId),

    actions({
        setActiveTab: (tab: AppMetricsTab) => ({ tab }),
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
    }),

    reducers({
        activeTab: [
            null as AppMetricsTab | null,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        dateFrom: [
            '-30d' as string,
            {
                setDateFrom: (_, { dateFrom }) => dateFrom,
            },
        ],
    }),

    loaders(({ values, props }) => ({
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
        appMetricsResponse: [
            null as AppMetricsResponse | null,
            {
                loadMetrics: async () => {
                    const params = toParams({ category: values.activeTab, date_from: values.dateFrom })
                    return await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/app_metrics/${props.pluginConfigId}?${params}`
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

    selectors(({ values }) => ({
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

        showTab: [
            () => [],
            () =>
                (tab: AppMetricsTab): boolean => {
                    if (values.pluginConfigLoading || !values.pluginConfig) {
                        return false
                    }
                    const capableMethods = values.pluginConfig.plugin_info.capabilities?.methods || []
                    if (tab === AppMetricsTab.HistoricalExports) {
                        return capableMethods.includes('exportEvents')
                    } else if (tab === AppMetricsTab.OnEvent && capableMethods.includes('exportEvents')) {
                        // Hide onEvent tab for plugins using exportEvents
                        return false
                    } else {
                        return capableMethods.includes(tab)
                    }
                },
        ],
    })),

    listeners(({ values, actions }) => ({
        loadPluginConfigSuccess: () => {
            // Delay showing of tabs until we know what is relevant for _this_ plugin
            if (!values.activeTab) {
                const [firstAppropriateTab] = INITIAL_TABS.filter((tab) => values.showTab(tab))
                actions.setActiveTab(firstAppropriateTab)
            }
        },
        setActiveTab: ({ tab }) => {
            if (tab === AppMetricsTab.HistoricalExports) {
                actions.loadHistoricalExports()
            } else {
                actions.loadMetrics()
            }
        },
        setDateFrom: () => {
            actions.loadMetrics()
        },
    })),

    actionToUrl(({ values, props }) => ({
        setActiveTab: () => {
            if (values.activeTab === AppMetricsTab.HistoricalExports) {
                return urls.appHistoricalExports(props.pluginConfigId)
            }

            return urls.appMetrics(props.pluginConfigId, values.activeTab ?? undefined)
        },
    })),

    urlToAction(({ values, actions }) => ({
        '/app/:pluginConfigId/:page': (
            url: Record<string, string | undefined>,
            params: Record<string, string | undefined>
        ) => {
            if (!values.pluginConfig) {
                actions.loadPluginConfig()
            }
            if (url.page === AppMetricsTab.HistoricalExports) {
                actions.setActiveTab(AppMetricsTab.HistoricalExports)
            } else if (params.tab && INITIAL_TABS.includes(params.tab as any)) {
                actions.setActiveTab(params.tab as AppMetricsTab)
            }
        },
    })),
])
