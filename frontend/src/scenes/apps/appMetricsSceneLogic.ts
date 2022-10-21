import { kea, key, props, path, actions, selectors, reducers, listeners } from 'kea'
import { loaders } from 'kea-loaders'

import type { appMetricsSceneLogicType } from './appMetricsSceneLogicType'
import { urls } from 'scenes/urls'
import { Breadcrumb, PluginConfigWithPluginInfo, UserBasicType } from '~/types'
import api from 'lib/api'
import { teamLogic } from '../teamLogic'
import { actionToUrl, urlToAction } from 'kea-router'
import { toParams } from 'lib/utils'
import { HISTORICAL_EXPORT_JOB_NAME_V2 } from 'scenes/plugins/edit/interface-jobs/PluginJobConfiguration'
import { interfaceJobsLogic, InterfaceJobsProps } from '../plugins/edit/interface-jobs/interfaceJobsLogic'

export interface AppMetricsLogicProps {
    /** Used as the logic's key */
    pluginConfigId: number
}

export interface AppMetricsUrlParams {
    tab?: AppMetricsTab
    from?: string
}

export enum AppMetricsTab {
    ProcessEvent = 'processEvent',
    OnEvent = 'onEvent',
    ExportEvents = 'exportEvents',
    ScheduledTask = 'scheduledTask',
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
    progress?: number
    failure_reason?: string
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

const DEFAULT_DATE_FROM = '-30d'
const INITIAL_TABS: Array<AppMetricsTab> = [
    AppMetricsTab.ProcessEvent,
    AppMetricsTab.OnEvent,
    AppMetricsTab.ExportEvents,
    AppMetricsTab.ScheduledTask,
]

export const appMetricsSceneLogic = kea<appMetricsSceneLogicType>([
    path((key) => ['scenes', 'apps', 'appMetricsSceneLogic', key]),
    props({} as AppMetricsLogicProps),
    key((props) => props.pluginConfigId),

    actions({
        setActiveTab: (tab: AppMetricsTab) => ({ tab }),
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
        openErrorDetailsModal: (errorType: string, category: string, jobId?: string) => ({
            errorType,
            category,
            jobId,
        }),
        closeErrorDetailsModal: true,
        openHistoricalExportModal: true,
    }),

    reducers({
        activeTab: [
            null as AppMetricsTab | null,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
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
        errorDetails: [
            [] as Array<AppMetricErrorDetail>,
            {
                openErrorDetailsModal: async ({ category, jobId, errorType }) => {
                    const params = toParams({ category, job_id: jobId, error_type: errorType })
                    const { result } = await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/app_metrics/${props.pluginConfigId}/error_details?${params}`
                    )
                    return result
                },
            },
        ],
    })),

    selectors(({ values, actions }) => ({
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
                    if (
                        values.pluginConfigLoading ||
                        !values.pluginConfig ||
                        !values.pluginConfig.plugin_info.capabilities
                    ) {
                        return false
                    }
                    const capabilities = values.pluginConfig.plugin_info.capabilities
                    const isExportEvents = capabilities.methods.includes('exportEvents')

                    if (tab === AppMetricsTab.HistoricalExports) {
                        return isExportEvents
                    } else if (tab === AppMetricsTab.OnEvent && isExportEvents) {
                        // Hide onEvent tab for plugins using exportEvents
                        // :KLUDGE: if plugin has `onEvent` in source, that's called/tracked but we can't check that here.
                        return false
                    } else if (tab === AppMetricsTab.ScheduledTask) {
                        // Show scheduled tasks summary if plugin has appropriate tasks.
                        // We hide scheduled tasks for plugins using exportEvents as it's automatically added.
                        // :KLUDGE: if plugin has `onEvent` in source, that's called/tracked but we can't check that here.
                        return (
                            !isExportEvents &&
                            ['runEveryMinute', 'runEveryHour', 'runEveryDay'].some((method) =>
                                capabilities.scheduled_tasks.includes(method)
                            )
                        )
                    } else {
                        return capabilities.methods.includes(tab)
                    }
                },
        ],

        interfaceJobsProps: [
            (s) => [s.pluginConfig],
            (pluginConfig): InterfaceJobsProps | null => {
                if (!pluginConfig || !pluginConfig.plugin_info.public_jobs || !pluginConfig?.enabled) {
                    return null
                }
                return {
                    jobName: HISTORICAL_EXPORT_JOB_NAME_V2,
                    jobSpec: pluginConfig.plugin_info.public_jobs[HISTORICAL_EXPORT_JOB_NAME_V2],
                    pluginConfigId: pluginConfig.id,
                    pluginId: pluginConfig.plugin,
                    onSubmit: actions.loadHistoricalExports,
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

        openHistoricalExportModal: () => {
            if (values.interfaceJobsProps) {
                interfaceJobsLogic(values.interfaceJobsProps).actions.setIsJobModalOpen(true)
            }
        },
    })),

    actionToUrl(({ values, props }) => ({
        setActiveTab: () => getUrl(values, props),
        setDateFrom: () => getUrl(values, props),
    })),

    urlToAction(({ values, actions, props }) => ({
        '/app/:pluginConfigId/:page': (url: Record<string, string | undefined>, params: AppMetricsUrlParams) => {
            // :KLUDGE: Only handle actions if this logic is active
            if (props.pluginConfigId === Number(url.pluginConfigId)) {
                if (!values.pluginConfig) {
                    actions.loadPluginConfig()
                }
                if (url.page === AppMetricsTab.HistoricalExports) {
                    actions.setActiveTab(AppMetricsTab.HistoricalExports)
                } else {
                    if (params.tab && INITIAL_TABS.includes(params.tab as any)) {
                        actions.setActiveTab(params.tab as AppMetricsTab)
                    }
                    if (params.from) {
                        actions.setDateFrom(params.from)
                    }
                }
            }
        },
    })),
])

function getUrl(values: appMetricsSceneLogicType['values'], props: appMetricsSceneLogicType['props']): string {
    if (values.activeTab === AppMetricsTab.HistoricalExports) {
        return urls.appHistoricalExports(props.pluginConfigId)
    }

    const params = {}
    if (values.activeTab) {
        params['tab'] = values.activeTab
    }
    if (values.dateFrom !== DEFAULT_DATE_FROM) {
        params['from'] = values.dateFrom
    }

    return urls.appMetrics(props.pluginConfigId, params)
}
