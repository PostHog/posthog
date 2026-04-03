/**
 * @deprecated This logic is frozen for legacy experiments only.
 *
 * This is a full duplication of experimentLogic.tsx adapted specifically for legacy experiments.
 * It handles experiments that use ExperimentTrendsQuery and ExperimentFunnelsQuery directly
 * instead of the newer ExperimentMetric wrapper.
 *
 * New features and improvements should be made in experimentLogic.tsx.
 * This file exists to maintain support for existing legacy experiments without
 * impacting the modernized experiment flow.
 */

import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { runWithLimit } from 'scenes/dashboard/dashboardUtils'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { urls } from 'scenes/urls'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { QUERY_TIMEOUT_ERROR_MESSAGE, performQuery } from '~/queries/query'
import {
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentTrendsQueryResponse,
    CachedLegacyExperimentQueryResponse,
    ExperimentFunnelsQuery,
    ExperimentTrendsQuery,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import {
    CohortType,
    CountPerActorMathType,
    Experiment,
    FunnelExperimentVariant,
    InsightType,
    MultivariateFlagVariant,
    PropertyMathType,
    TrendExperimentVariant,
} from '~/types'

import { EXPERIMENT_AUTO_REFRESH_INITIAL_INTERVAL_SECONDS, MetricInsightId } from '../constants'
import {
    experimentsLogic,
    getShippedVariantKey,
    hasEnded,
    isLaunched,
    isSingleVariantShipped,
} from '../experimentsLogic'
import { holdoutsLogic } from '../holdoutsLogic'
import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'
import { sharedMetricsLogic } from '../SharedMetrics/sharedMetricsLogic'
import {
    legacyConversionRateForVariant,
    legacyExpectedRunningTime,
    legacyGetSignificanceDetails,
    legacyMinimumSampleSizePerVariant,
    legacyRecommendedExposureForCountData,
} from './calculations/legacyExperimentCalculations'
import type { legacyExperimentLogicType } from './legacyExperimentLogicType'

export const DEFAULT_MDE = 30

export const FORM_MODES = {
    create: 'create',
    duplicate: 'duplicate',
    update: 'update',
} as const

export type FormModes = (typeof FORM_MODES)[keyof typeof FORM_MODES]

export interface LegacyExperimentLogicProps {
    experimentId?: Experiment['id']
    formMode?: FormModes
    tabId?: string
}

export type ExperimentTriggeredBy = 'page_load' | 'manual' | 'auto_refresh' | 'config_change'

function generateRefreshId(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID()
    }
    // Fallback for environments without crypto.randomUUID (e.g., jsdom tests)
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0
        const v = c === 'x' ? r : (r & 0x3) | 0x8
        return v.toString(16)
    })
}

interface MetricLoadingConfig {
    metrics: (ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
    experimentId: Experiment['id']
    refresh?: boolean
    teamId?: number | null
    refreshId: string
    isPrimary: boolean
    isRetry: boolean
    metricIndexOffset: number
    orderedUuids?: string[] | null
    onSetLegacyResults: (
        results: (
            | CachedLegacyExperimentQueryResponse
            | CachedExperimentTrendsQueryResponse
            | CachedExperimentFunnelsQueryResponse
            | null
        )[]
    ) => void
    onSetErrors: (errors: any[]) => void
}

interface MetricLoadingSummary {
    successfulCount: number
    erroredCount: number
    cachedCount: number
}

const OUT_OF_MEMORY_ERROR_CODES = new Set(['memory_limit_exceeded', 'query_memory_limit_exceeded'])

function isOutOfMemoryError(errorCode: string | null, errorMessage: string | null): boolean {
    if (errorCode && OUT_OF_MEMORY_ERROR_CODES.has(errorCode)) {
        return true
    }

    return !!errorMessage && /(out of memory|memory limit exceeded|exceeded memory limit)/i.test(errorMessage)
}

function parseMetricErrorDetail(error: any): { detail: any; hasDiagnostics: boolean } {
    const errorDetailText = typeof error.detail === 'string' ? error.detail : null
    const errorDetailMatch = errorDetailText?.match(/\{.*\}/)

    if (!errorDetailMatch) {
        return { detail: error.detail || error.message, hasDiagnostics: false }
    }

    try {
        return { detail: JSON.parse(errorDetailMatch[0]), hasDiagnostics: true }
    } catch {
        return { detail: error.detail || error.message, hasDiagnostics: false }
    }
}

function isTimeoutError(errorDetail: unknown, errorMessage: string | null, statusCode: number | null): boolean {
    if (statusCode === 504) {
        return true
    }

    return errorDetail === QUERY_TIMEOUT_ERROR_MESSAGE || errorMessage === QUERY_TIMEOUT_ERROR_MESSAGE
}

function classifyError(
    errorDetail: unknown,
    errorMessage: string | null,
    errorCode: string | null,
    statusCode: number | null
): 'timeout' | 'out_of_memory' | 'server_error' | 'network_error' | 'unknown' {
    if (isTimeoutError(errorDetail, errorMessage, statusCode)) {
        return 'timeout'
    }
    if (isOutOfMemoryError(errorCode, errorMessage)) {
        return 'out_of_memory'
    }
    if (statusCode !== null && statusCode >= 500) {
        return 'server_error'
    }
    if (statusCode === 0 || errorCode === 'network_error' || errorMessage?.includes('NetworkError')) {
        return 'network_error'
    }
    return 'unknown'
}

/**
 * Returns metric indices in display order. Metrics whose UUID appears in
 * orderedUuids come first (in that order), followed by any remaining metrics
 * in their original array position. Each entry is the original index into the
 * metrics array so callers can write results to the correct positional slot.
 */
export function getDisplayOrderedIndices(
    metrics: { uuid?: string }[],
    orderedUuids: string[] | null | undefined
): number[] {
    if (!orderedUuids || orderedUuids.length === 0) {
        return metrics.map((_, i) => i)
    }

    const uuidToIndex = new Map<string, number>()
    for (let i = 0; i < metrics.length; i++) {
        const uuid = metrics[i].uuid
        if (uuid) {
            uuidToIndex.set(uuid, i)
        }
    }

    const ordered: number[] = []
    const seen = new Set<number>()

    for (const uuid of orderedUuids) {
        const idx = uuidToIndex.get(uuid)
        if (idx !== undefined && !seen.has(idx)) {
            ordered.push(idx)
            seen.add(idx)
        }
    }

    for (let i = 0; i < metrics.length; i++) {
        if (!seen.has(i)) {
            ordered.push(i)
        }
    }

    return ordered
}

// Max concurrent metric queries
const METRIC_QUERY_CONCURRENCY_LIMIT = 10

const loadMetrics = async ({
    metrics,
    experimentId,
    refresh,
    teamId,
    refreshId,
    isPrimary,
    isRetry,
    metricIndexOffset,
    orderedUuids,
    onSetLegacyResults,
    onSetErrors,
}: MetricLoadingConfig): Promise<MetricLoadingSummary> => {
    const legacyResults: (
        | CachedLegacyExperimentQueryResponse
        | CachedExperimentTrendsQueryResponse
        | CachedExperimentFunnelsQueryResponse
        | null
    )[] = []

    const currentErrors = Array.from({ length: metrics.length }, () => null)

    let successfulCount = 0
    let erroredCount = 0
    let cachedCount = 0

    const displayOrder = getDisplayOrderedIndices(metrics, orderedUuids)

    const tasks = displayOrder.map((originalIndex) => {
        const metric = metrics[originalIndex]
        return async (): Promise<void> => {
            let response: any = null
            const startTime = performance.now()
            const metricIndex = metricIndexOffset + originalIndex
            const metricKind = metric.kind || 'unknown'

            try {
                const queryWithExperimentId = {
                    ...metric,
                    experiment_id: experimentId,
                }
                response = await performQuery(
                    setLatestVersionsOnQuery(queryWithExperimentId),
                    undefined,
                    refresh ? 'force_async' : 'async'
                )

                const durationMs = Math.round(performance.now() - startTime)
                const isCached = !!response?.is_cached

                legacyResults[originalIndex] = {
                    ...response,
                    fakeInsightId: Math.random().toString(36).substring(2, 15),
                } as (CachedExperimentTrendsQueryResponse | CachedExperimentFunnelsQueryResponse) & {
                    fakeInsightId: string
                }
                onSetLegacyResults([...legacyResults])

                successfulCount++
                if (isCached) {
                    cachedCount++
                }

                eventUsageLogic.actions.reportExperimentMetricFinished(
                    experimentId,
                    metric,
                    teamId,
                    response?.query_status?.id || null,
                    {
                        duration_ms: durationMs,
                        is_cached: isCached,
                        metric_index: metricIndex,
                        is_primary: isPrimary,
                        is_retry: isRetry,
                        refresh_id: refreshId,
                        metric_kind: metricKind,
                    }
                )
            } catch (error: any) {
                const durationMs = Math.round(performance.now() - startTime)
                const errorCode = typeof error.code === 'string' ? error.code : null
                const statusCode = typeof error.status === 'number' ? error.status : null
                const errorMessage =
                    typeof error.detail === 'string'
                        ? error.detail
                        : typeof error.message === 'string'
                          ? error.message
                          : null
                const { detail: errorDetail, hasDiagnostics } = parseMetricErrorDetail(error)
                const queryId = response?.query_status?.id || error.queryId || null
                const errorType = classifyError(errorDetail, errorMessage, errorCode, statusCode)

                currentErrors[originalIndex] = {
                    detail: errorDetail,
                    statusCode,
                    hasDiagnostics,
                    code: errorCode,
                    queryId,
                    timestamp: Date.now(),
                }
                onSetErrors(currentErrors)

                erroredCount++

                // Keep backwards-compatible events firing
                if (errorType === 'timeout') {
                    eventUsageLogic.actions.reportExperimentMetricTimeout(experimentId, metric, teamId, queryId)
                } else if (errorType === 'out_of_memory') {
                    eventUsageLogic.actions.reportExperimentMetricOutOfMemory(
                        experimentId,
                        metric,
                        teamId,
                        queryId,
                        errorCode,
                        errorMessage
                    )
                }

                // Unified error event for all error types
                eventUsageLogic.actions.reportExperimentMetricError(experimentId, metric, teamId, queryId, {
                    duration_ms: durationMs,
                    metric_index: metricIndex,
                    is_primary: isPrimary,
                    is_retry: isRetry,
                    refresh_id: refreshId,
                    metric_kind: metricKind,
                    error_type: errorType,
                    error_code: errorCode,
                    error_message: errorMessage,
                    status_code: statusCode,
                })

                legacyResults[originalIndex] = null
                onSetLegacyResults([...legacyResults])
            }
        }
    })

    await runWithLimit(tasks, METRIC_QUERY_CONCURRENCY_LIMIT)

    return { successfulCount, erroredCount, cachedCount }
}

export const legacyExperimentLogic = kea<legacyExperimentLogicType>([
    props({} as LegacyExperimentLogicProps),
    key((props) => {
        const baseKey = props.experimentId ?? 'new'
        return `${baseKey}${props.tabId ? `-${props.tabId}` : ''}`
    }),
    path((key) => ['scenes', 'experiment', 'legacy', 'legacyExperimentLogic', key]),
    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['aggregationLabel', 'groupTypes', 'showGroupsOptions'],
            featureFlagLogic,
            ['featureFlags'],
            holdoutsLogic,
            ['holdouts'],
            billingLogic,
            ['billing'],
            funnelDataLogic({ dashboardItemId: MetricInsightId.Funnels }),
            ['results as funnelResults', 'conversionMetrics'],
            trendsDataLogic({ dashboardItemId: MetricInsightId.Trends }),
            ['results as trendResults'],
            insightDataLogic({ dashboardItemId: MetricInsightId.Trends }),
            ['insightDataLoading as trendMetricInsightLoading'],
            insightDataLogic({ dashboardItemId: MetricInsightId.Funnels }),
            ['insightDataLoading as funnelMetricInsightLoading'],
            sharedMetricsLogic,
            ['sharedMetrics'],
        ],
        actions: [
            experimentsLogic,
            ['updateExperiments', 'addToExperiments'],
            eventUsageLogic,
            [
                'reportExperimentCreated',
                'reportExperimentViewed',
                'reportExperimentExposureCohortCreated',
                'reportExperimentVariantScreenshotUploaded',
                'reportExperimentResultsLoadingTimeout',
                'reportExperimentReleaseConditionsViewed',
                'reportExperimentHoldoutAssigned',
                'reportExperimentSharedMetricAssigned',
                'reportExperimentDashboardCreated',
                'reportExperimentMetricTimeout',
                'reportExperimentTimeseriesViewed',
                'reportExperimentTimeseriesRecalculated',
                'reportExperimentAiSummaryRequested',
                'reportExperimentSessionReplaySummaryRequested',
                'reportExperimentMetricsRefreshed',
                'reportExperimentAutoRefreshToggled',
                'reportExperimentMetricBreakdownAdded',
                'reportExperimentMetricBreakdownRemoved',
            ],
            teamLogic,
            ['addProductIntent'],
            featureFlagsLogic,
            ['updateFlag'],
        ],
    })),
    actions({
        setExperimentMissing: true,
        setExperiment: (experiment: Partial<Experiment>) => ({ experiment }),
        setExposureAndSampleSize: (exposure: number, sampleSize: number) => ({ exposure, sampleSize }),
        refreshExperimentResults: (forceRefresh?: boolean, triggeredBy?: ExperimentTriggeredBy) => ({
            forceRefresh,
            triggeredBy: triggeredBy ?? 'manual',
        }),
        setLegacyPrimaryMetricsResults: (
            results: (
                | CachedLegacyExperimentQueryResponse
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null
            )[]
        ) => ({ results }),
        setPrimaryMetricsResultsLoading: (loading: boolean) => ({ loading }),
        loadPrimaryMetricsResults: (refresh?: boolean, refreshId?: string) => ({ refresh, refreshId }),
        setPrimaryMetricsResultsErrors: (errors: any[]) => ({ errors }),
        retryPrimaryMetric: (index: number) => ({ index }),
        setLegacySecondaryMetricsResults: (
            results: (
                | CachedLegacyExperimentQueryResponse
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null
            )[]
        ) => ({ results }),
        setSecondaryMetricsResultsLoading: (loading: boolean) => ({ loading }),
        loadSecondaryMetricsResults: (refresh?: boolean, refreshId?: string) => ({ refresh, refreshId }),
        setSecondaryMetricsResultsErrors: (errors: any[]) => ({ errors }),
        retrySecondaryMetric: (index: number) => ({ index }),
        addSharedMetricsToExperiment: (
            sharedMetricIds: SharedMetric['id'][],
            metadata: { type: 'primary' | 'secondary' }
        ) => ({
            sharedMetricIds,
            metadata,
        }),
        removeSharedMetricFromExperiment: (sharedMetricId: SharedMetric['id']) => ({ sharedMetricId }),
        restoreUnmodifiedExperiment: true,
        setAutoRefresh: (enabled: boolean, interval: number) => ({ enabled, interval }),
        resetAutoRefreshInterval: true,
        stopAutoRefreshInterval: true,
        setPageVisibility: (visible: boolean) => ({ visible }),
        clearMetricsResults: true,
    }),
    reducers({
        experiment: [
            null as Experiment | null,
            {
                setExperiment: (state, { experiment }) => {
                    if (!state) {
                        return experiment as Experiment
                    }
                    return { ...state, ...experiment }
                },
            },
        ],
        experimentMissing: [
            false,
            {
                setExperimentMissing: () => true,
            },
        ],
        legacyPrimaryMetricsResults: [
            [] as (
                | CachedLegacyExperimentQueryResponse
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null
            )[],
            {
                setLegacyPrimaryMetricsResults: (_, { results }) => results,
                clearMetricsResults: () => [],
            },
        ],
        primaryMetricsResultsLoading: [
            false,
            {
                setPrimaryMetricsResultsLoading: (_, { loading }) => loading,
            },
        ],
        primaryMetricsResultsErrors: [
            [] as any[],
            {
                setPrimaryMetricsResultsErrors: (_, { errors }) => errors,
                loadPrimaryMetricsResults: () => [],
                loadExperiment: () => [],
                clearMetricsResults: () => [],
            },
        ],
        legacySecondaryMetricsResults: [
            [] as (
                | CachedLegacyExperimentQueryResponse
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null
            )[],
            {
                setLegacySecondaryMetricsResults: (_, { results }) => results,
                clearMetricsResults: () => [],
            },
        ],
        secondaryMetricsResultsLoading: [
            false,
            {
                setSecondaryMetricsResultsLoading: (_, { loading }) => loading,
            },
        ],
        secondaryMetricsResultsErrors: [
            [] as any[],
            {
                setSecondaryMetricsResultsErrors: (_, { errors }) => errors,
                loadSecondaryMetricsResults: () => [],
                loadExperiment: () => [],
                clearMetricsResults: () => [],
            },
        ],
        autoRefresh: [
            {
                interval: EXPERIMENT_AUTO_REFRESH_INITIAL_INTERVAL_SECONDS,
                enabled: false,
            } as { interval: number; enabled: boolean },
            { persist: true, prefix: '2_' },
            {
                setAutoRefresh: (_, { enabled, interval }) => ({ enabled, interval }),
            },
        ],
        isPageVisible: [
            true as boolean,
            {
                setPageVisibility: (_, { visible }) => visible,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        experiment: {
            loadExperiment: async ({ triggeredBy }: { triggeredBy?: ExperimentTriggeredBy } = {}) => {
                void triggeredBy
                if (values.experimentId && values.experimentId !== 'new') {
                    try {
                        const response: Experiment = await api.get(
                            `api/projects/${values.currentProjectId}/experiments/${values.experimentId}`
                        )
                        return response
                    } catch (error: any) {
                        if (error.status === 404) {
                            actions.setExperimentMissing()
                        } else {
                            throw error
                        }
                    }
                }
                return null
            },
            updateExperiment: async (update: Partial<Experiment>) => {
                const response: Experiment = await api.update(
                    `api/projects/${values.currentProjectId}/experiments/${values.experimentId}`,
                    update
                )
                refreshTreeItem('experiment', String(values.experimentId))
                return response
            },
        },
        exposureCohort: [
            null as CohortType | null,
            {
                createExposureCohort: async () => {
                    if (values.experimentId && values.experimentId !== 'new' && values.experimentId !== 'web') {
                        return (await api.experiments.createExposureCohort(values.experimentId)).cohort
                    }
                    return null
                },
            },
        ],
    })),
    listeners(({ values, actions, asyncActions, cache }) => ({
        beforeUnmount: () => {
            actions.stopAutoRefreshInterval()
        },
        loadExperimentSuccess: async ({ experiment, payload }) => {
            const duration = experiment?.start_date ? dayjs().diff(experiment.start_date, 'second') : null
            experiment && actions.reportExperimentViewed(experiment, duration)

            // Load metrics for launched experiments
            if (experiment && isLaunched(experiment)) {
                actions.refreshExperimentResults(false, payload?.triggeredBy ?? 'manual')
            }
        },
        updateExperimentSuccess: async ({ experiment }) => {
            actions.updateExperiments(experiment)
            if (isLaunched(experiment)) {
                actions.refreshExperimentResults(true, 'config_change')
            }
        },
        refreshExperimentResults: async ({ forceRefresh, triggeredBy }) => {
            const refreshId = generateRefreshId()
            const refreshStart = performance.now()
            const summaries: MetricLoadingSummary[] = []
            cache.refreshSummariesById = cache.refreshSummariesById ?? {}
            cache.refreshSummariesById[refreshId] = summaries

            try {
                await Promise.all([
                    asyncActions.loadPrimaryMetricsResults(forceRefresh, refreshId),
                    asyncActions.loadSecondaryMetricsResults(forceRefresh, refreshId),
                ])
            } finally {
                const totalDurationMs = Math.round(performance.now() - refreshStart)
                const refreshSummaries: MetricLoadingSummary[] = cache.refreshSummariesById?.[refreshId] ?? []
                if (cache.refreshSummariesById) {
                    delete cache.refreshSummariesById[refreshId]
                }

                const primaryCount = values.experiment?.metrics?.length || 0
                const secondaryCount = values.experiment?.metrics_secondary?.length || 0
                const successfulCount = refreshSummaries.reduce((sum, s) => sum + s.successfulCount, 0)
                const erroredCount = refreshSummaries.reduce((sum, s) => sum + s.erroredCount, 0)
                const cachedCount = refreshSummaries.reduce((sum, s) => sum + s.cachedCount, 0)

                eventUsageLogic.actions.reportExperimentResultsRefreshCompleted(
                    values.experimentId,
                    values.currentTeamId,
                    {
                        total_duration_ms: totalDurationMs,
                        primary_metrics_count: primaryCount,
                        secondary_metrics_count: secondaryCount,
                        successful_count: successfulCount,
                        errored_count: erroredCount,
                        cached_count: cachedCount,
                        triggered_by: triggeredBy ?? 'manual',
                        force_refresh: !!forceRefresh,
                        refresh_id: refreshId,
                        experiment_duration_hours: values.experiment?.start_date
                            ? Math.round(
                                  (Date.now() - new Date(values.experiment.start_date).getTime()) / (1000 * 60 * 60)
                              )
                            : null,
                        experiment_status: values.experiment?.status ?? null,
                        total_metrics_count: primaryCount + secondaryCount,
                    }
                )

                // Only set up auto-refresh if enabled AND page is visible
                if (
                    values.experiment &&
                    values.autoRefresh.enabled &&
                    isLaunched(values.experiment) &&
                    values.isPageVisible
                ) {
                    actions.resetAutoRefreshInterval()
                }
            }
        },
        addSharedMetricsToExperiment: async ({ sharedMetricIds, metadata }) => {
            const existingMetricsIds =
                values.experiment?.saved_metrics?.map((sharedMetric) => ({
                    id: sharedMetric.saved_metric,
                    metadata: sharedMetric.metadata,
                })) || []

            const newMetricsIds = sharedMetricIds.map((id: SharedMetric['id']) => ({ id, metadata }))
            newMetricsIds.forEach((metricId) => {
                const metric = values.sharedMetrics.find((m: SharedMetric) => m.id === metricId.id)
                if (metric) {
                    actions.reportExperimentSharedMetricAssigned(values.experimentId, metric)
                }
            })
            const combinedMetricsIds = [...existingMetricsIds, ...newMetricsIds]

            await api.update(`api/projects/${values.currentProjectId}/experiments/${values.experimentId}`, {
                saved_metrics_ids: combinedMetricsIds,
            })

            actions.loadExperiment({ triggeredBy: 'config_change' })
        },
        removeSharedMetricFromExperiment: async ({ sharedMetricId }) => {
            const sharedMetricsIds =
                values.experiment?.saved_metrics
                    ?.filter((sharedMetric) => sharedMetric.saved_metric !== sharedMetricId)
                    .map((sharedMetric) => ({
                        id: sharedMetric.saved_metric,
                        metadata: sharedMetric.metadata,
                    })) || []

            await api.update(`api/projects/${values.currentProjectId}/experiments/${values.experimentId}`, {
                saved_metrics_ids: sharedMetricsIds,
            })

            actions.loadExperiment({ triggeredBy: 'config_change' })
        },
        createExposureCohortSuccess: ({ exposureCohort }) => {
            if (exposureCohort && exposureCohort.id !== 'new') {
                cohortsModel.actions.cohortCreated(exposureCohort)
                actions.reportExperimentExposureCohortCreated(values.experiment, exposureCohort)
                actions.setExperiment({ exposure_cohort: exposureCohort.id })
                lemonToast.success('Exposure cohort created successfully', {
                    button: {
                        label: 'View cohort',
                        action: () => router.actions.push(urls.cohort(exposureCohort.id)),
                    },
                })
            }
        },
        loadPrimaryMetricsResults: async ({ refresh, refreshId }: { refresh?: boolean; refreshId?: string }) => {
            actions.setPrimaryMetricsResultsLoading(true)
            actions.setLegacyPrimaryMetricsResults([])

            const metrics = values.experiment?.metrics || []

            const resolvedRefreshId = refreshId || generateRefreshId()
            const summary = await loadMetrics({
                metrics: metrics as (ExperimentTrendsQuery | ExperimentFunnelsQuery)[],
                experimentId: values.experimentId,
                refresh,
                teamId: values.currentTeamId,
                refreshId: resolvedRefreshId,
                isPrimary: true,
                isRetry: false,
                metricIndexOffset: 0,
                orderedUuids: values.experiment?.primary_metrics_ordered_uuids,
                onSetLegacyResults: actions.setLegacyPrimaryMetricsResults,
                onSetErrors: actions.setPrimaryMetricsResultsErrors,
            })

            const refreshSummaries = cache.refreshSummariesById?.[resolvedRefreshId]
            if (refreshSummaries) {
                refreshSummaries.push(summary)
            }

            actions.setPrimaryMetricsResultsLoading(false)
        },
        loadSecondaryMetricsResults: async ({ refresh, refreshId }: { refresh?: boolean; refreshId?: string }) => {
            actions.setSecondaryMetricsResultsLoading(true)
            actions.setLegacySecondaryMetricsResults([])

            const secondaryMetrics = values.experiment?.metrics_secondary || []

            const resolvedRefreshId = refreshId || generateRefreshId()
            const summary = await loadMetrics({
                metrics: secondaryMetrics as (ExperimentTrendsQuery | ExperimentFunnelsQuery)[],
                experimentId: values.experimentId,
                refresh,
                teamId: values.currentTeamId,
                refreshId: resolvedRefreshId,
                isPrimary: false,
                isRetry: false,
                metricIndexOffset: 0,
                orderedUuids: values.experiment?.secondary_metrics_ordered_uuids,
                onSetLegacyResults: actions.setLegacySecondaryMetricsResults,
                onSetErrors: actions.setSecondaryMetricsResultsErrors,
            })

            const refreshSummaries = cache.refreshSummariesById?.[resolvedRefreshId]
            if (refreshSummaries) {
                refreshSummaries.push(summary)
            }

            actions.setSecondaryMetricsResultsLoading(false)
        },
        retryPrimaryMetric: async ({ index }: { index: number }) => {
            const currentErrors = [...values.primaryMetricsResultsErrors]
            currentErrors[index] = null
            actions.setPrimaryMetricsResultsErrors(currentErrors)

            const metrics = values.experiment?.metrics || []
            const metricToRetry = metrics[index]
            if (!metricToRetry) {
                return
            }

            const singleMetricArray = [metricToRetry]
            const currentLegacyResults = [...values.legacyPrimaryMetricsResults]

            await loadMetrics({
                metrics: singleMetricArray as (ExperimentTrendsQuery | ExperimentFunnelsQuery)[],
                experimentId: values.experimentId,
                refresh: true,
                teamId: values.currentTeamId,
                refreshId: generateRefreshId(),
                isPrimary: true,
                isRetry: true,
                metricIndexOffset: index,
                onSetLegacyResults: (results) => {
                    currentLegacyResults[index] = results[0]
                    actions.setLegacyPrimaryMetricsResults(currentLegacyResults)
                },
                onSetErrors: (errors) => {
                    currentErrors[index] = errors[0]
                    actions.setPrimaryMetricsResultsErrors(currentErrors)
                },
            })
        },
        retrySecondaryMetric: async ({ index }: { index: number }) => {
            const currentErrors = [...values.secondaryMetricsResultsErrors]
            currentErrors[index] = null
            actions.setSecondaryMetricsResultsErrors(currentErrors)

            const metrics = values.experiment?.metrics_secondary || []
            const metricToRetry = metrics[index]
            if (!metricToRetry) {
                return
            }

            const singleMetricArray = [metricToRetry]
            const currentLegacyResults = [...values.legacySecondaryMetricsResults]

            await loadMetrics({
                metrics: singleMetricArray as (ExperimentTrendsQuery | ExperimentFunnelsQuery)[],
                experimentId: values.experimentId,
                refresh: true,
                teamId: values.currentTeamId,
                refreshId: generateRefreshId(),
                isPrimary: false,
                isRetry: true,
                metricIndexOffset: index,
                onSetLegacyResults: (results) => {
                    currentLegacyResults[index] = results[0]
                    actions.setLegacySecondaryMetricsResults(currentLegacyResults)
                },
                onSetErrors: (errors) => {
                    currentErrors[index] = errors[0]
                    actions.setSecondaryMetricsResultsErrors(currentErrors)
                },
            })
        },
        setPageVisibility: ({ visible }) => {
            if (!visible) {
                actions.stopAutoRefreshInterval()
            } else if (
                values.experiment &&
                values.autoRefresh.enabled &&
                isLaunched(values.experiment) &&
                !hasEnded(values.experiment)
            ) {
                actions.resetAutoRefreshInterval()
            }
        },
        resetAutoRefreshInterval: () => {
            actions.stopAutoRefreshInterval()

            if (!values.autoRefresh.enabled) {
                return
            }

            if (!values.experiment || !isLaunched(values.experiment) || hasEnded(values.experiment)) {
                return
            }

            if (!values.isPageVisible) {
                return
            }

            const intervalMs = values.autoRefresh.interval * 1000
            const intervalId = setInterval(() => {
                if (!values.isPageVisible) {
                    actions.stopAutoRefreshInterval()
                    return
                }
                actions.refreshExperimentResults(true, 'auto_refresh')
            }, intervalMs)

            cache.autoRefreshInterval = intervalId
        },
        stopAutoRefreshInterval: () => {
            if (cache.autoRefreshInterval) {
                clearInterval(cache.autoRefreshInterval)
                cache.autoRefreshInterval = null
            }
        },
    })),
    selectors({
        props: [() => [(_, props) => props], (props) => props],
        experimentId: [
            () => [(_, props) => props.experimentId ?? 'new'],
            (experimentId): Experiment['id'] => experimentId,
        ],
        formMode: [() => [(_, props) => props.formMode ?? FORM_MODES.update], (formMode): FormModes => formMode],
        getInsightType: [
            () => [],
            () =>
                (metric: ExperimentTrendsQuery | ExperimentFunnelsQuery | undefined): InsightType => {
                    return metric?.kind === 'ExperimentTrendsQuery' ? InsightType.TRENDS : InsightType.FUNNELS
                },
        ],
        isExperimentLaunched: [
            (s) => [s.experiment],
            (experiment): boolean => {
                return !!experiment && isLaunched(experiment)
            },
        ],
        variants: [
            (s) => [s.experiment],
            (experiment): MultivariateFlagVariant[] => {
                return experiment?.parameters?.feature_flag_variants || []
            },
        ],
        experimentMathAggregationForTrends: [
            (s) => [s.experiment],
            (experiment) => (): PropertyMathType | CountPerActorMathType | undefined => {
                const query = experiment?.metrics?.[0] as ExperimentTrendsQuery
                if (!query) {
                    return undefined
                }
                const entities = query.count_query?.series || []

                const userMathValue = entities.filter((entity) =>
                    Object.values(CountPerActorMathType).includes(entity?.math as CountPerActorMathType)
                )[0]?.math

                const targetValues = Object.values(PropertyMathType).filter((value) => value !== PropertyMathType.Sum)

                const propertyMathValue = entities.filter((entity) =>
                    (targetValues as readonly PropertyMathType[]).includes(entity?.math as PropertyMathType)
                )[0]?.math

                return (userMathValue ?? propertyMathValue) as PropertyMathType | CountPerActorMathType | undefined
            },
        ],
        minimumDetectableEffect: [
            (s) => [s.experiment],
            (newExperiment): number => {
                return newExperiment?.parameters?.minimum_detectable_effect ?? DEFAULT_MDE
            },
        ],
        isPrimaryMetricSignificant: [
            (s) => [s.legacyPrimaryMetricsResults, s.experiment],
            (
                legacyPrimaryMetricsResults: (
                    | CachedLegacyExperimentQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                    | CachedExperimentTrendsQueryResponse
                    | null
                )[],
                experiment: Experiment | null
            ) =>
                (metricUuid: string): boolean => {
                    if (!experiment) {
                        return false
                    }
                    const index = experiment.metrics.findIndex((m) => m.uuid === metricUuid)
                    if (index === -1) {
                        return false
                    }

                    const result = legacyPrimaryMetricsResults?.[index]
                    if (!result) {
                        return false
                    }

                    return result.significant || false
                },
        ],
        isSecondaryMetricSignificant: [
            (s) => [s.legacySecondaryMetricsResults, s.experiment],
            (
                legacySecondaryMetricsResults: (
                    | CachedLegacyExperimentQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                    | CachedExperimentTrendsQueryResponse
                    | null
                )[],
                experiment: Experiment | null
            ) =>
                (metricUuid: string): boolean => {
                    if (!experiment) {
                        return false
                    }
                    const index = experiment.metrics_secondary.findIndex((m) => m.uuid === metricUuid)
                    if (index === -1) {
                        return false
                    }

                    const result = legacySecondaryMetricsResults?.[index]
                    if (!result) {
                        return false
                    }

                    return result.significant || false
                },
        ],
        getSignificanceDetails: [
            (s) => [s.legacyPrimaryMetricsResults, s.experiment],
            (
                legacyPrimaryMetricsResults: (
                    | CachedLegacyExperimentQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                    | CachedExperimentTrendsQueryResponse
                    | null
                )[],
                experiment: Experiment | null
            ) =>
                (metricUuid: string): string => {
                    if (!experiment) {
                        return ''
                    }
                    const index = experiment.metrics.findIndex((m) => m.uuid === metricUuid)
                    if (index === -1) {
                        return ''
                    }

                    const results = legacyPrimaryMetricsResults?.[index]
                    return legacyGetSignificanceDetails(results)
                },
        ],
        minimumDetectableChange: [
            (s) => [s.legacyPrimaryMetricsResults, s.experiment],
            (
                legacyPrimaryMetricsResults: (
                    | CachedLegacyExperimentQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                    | CachedExperimentTrendsQueryResponse
                    | null
                )[],
                experiment: Experiment | null
            ) =>
                (metricUuid: string): number => {
                    if (!experiment) {
                        return 0
                    }
                    const index = experiment.metrics.findIndex((m) => m.uuid === metricUuid)
                    if (index === -1) {
                        return 0
                    }

                    const result = legacyPrimaryMetricsResults?.[index]
                    if (!result) {
                        return 0
                    }

                    return result.expected_loss || 0
                },
        ],
        recommendedSampleSize: [
            (s) => [s.conversionMetrics, s.variants, s.minimumDetectableEffect],
            (conversionMetrics, variants, minimumDetectableEffect): number => {
                const conversionRate = conversionMetrics.totalRate * 100
                const sampleSizePerVariant = legacyMinimumSampleSizePerVariant(minimumDetectableEffect, conversionRate)
                const sampleSize = sampleSizePerVariant * variants.length
                return sampleSize
            },
        ],
        recommendedRunningTime: [
            (s) => [
                s.experiment,
                s.variants,
                s.getInsightType,
                s.firstPrimaryMetric,
                s.funnelResults,
                s.conversionMetrics,
                s.trendResults,
                s.minimumDetectableEffect,
            ],
            (
                experiment,
                variants,
                getInsightType,
                firstPrimaryMetric,
                funnelResults,
                conversionMetrics,
                trendResults,
                minimumDetectableEffect
            ): number => {
                if (getInsightType(firstPrimaryMetric) === InsightType.FUNNELS) {
                    const currentDuration = dayjs().diff(dayjs(experiment?.start_date), 'hour')
                    let funnelEntrants: number | undefined
                    if (Array.isArray(funnelResults) && funnelResults[0]) {
                        const firstFunnelEntry = funnelResults[0]

                        funnelEntrants = Array.isArray(firstFunnelEntry)
                            ? firstFunnelEntry[0].count
                            : firstFunnelEntry.count
                    }

                    const conversionRate = conversionMetrics.totalRate * 100
                    const sampleSizePerVariant = legacyMinimumSampleSizePerVariant(
                        minimumDetectableEffect,
                        conversionRate
                    )
                    const funnelSampleSize = sampleSizePerVariant * variants.length
                    if (experiment?.start_date) {
                        return legacyExpectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0, currentDuration)
                    }
                    return legacyExpectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0)
                }

                const trendCount = trendResults[0]?.count
                const runningTime = legacyRecommendedExposureForCountData(minimumDetectableEffect, trendCount)
                return runningTime
            },
        ],
        expectedRunningTime: [
            (s) => [s.recommendedRunningTime],
            (recommendedRunningTime): number => recommendedRunningTime,
        ],
        tabularExperimentResults: [
            (s) => [s.experiment, s.legacyPrimaryMetricsResults, s.legacySecondaryMetricsResults, s.getInsightType],
            (
                experiment,
                legacyPrimaryMetricsResults: (
                    | CachedLegacyExperimentQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                    | CachedExperimentTrendsQueryResponse
                    | null
                )[],
                legacySecondaryMetricsResults: (
                    | CachedLegacyExperimentQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                    | CachedExperimentTrendsQueryResponse
                    | null
                )[],
                getInsightType
            ) =>
                (metricIdentifier: number | string = 0, isSecondary: boolean = false): any[] => {
                    if (!experiment) {
                        return []
                    }
                    let index: number
                    if (typeof metricIdentifier === 'string') {
                        const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
                        index = metrics.findIndex((m) => m.uuid === metricIdentifier)
                        if (index === -1) {
                            return []
                        }
                    } else {
                        index = metricIdentifier
                    }

                    const tabularResults = []
                    const metricType = isSecondary
                        ? getInsightType(experiment.metrics_secondary[index])
                        : getInsightType(experiment.metrics[index])
                    const result = isSecondary
                        ? legacySecondaryMetricsResults[index]
                        : legacyPrimaryMetricsResults[index]

                    if (result) {
                        for (const variantObj of result.variants) {
                            if (metricType === InsightType.FUNNELS) {
                                const { key, success_count, failure_count } = variantObj as FunnelExperimentVariant
                                tabularResults.push({ key, success_count, failure_count })
                            } else if (metricType === InsightType.TRENDS) {
                                const { key, count, exposure, absolute_exposure } = variantObj as TrendExperimentVariant
                                tabularResults.push({ key, count, exposure, absolute_exposure })
                            }
                        }
                    }

                    if (experiment.feature_flag?.filters.multivariate?.variants) {
                        for (const { key } of experiment.feature_flag.filters.multivariate.variants) {
                            if (tabularResults.find((variantObj) => variantObj.key === key)) {
                                continue
                            }

                            if (metricType === InsightType.FUNNELS) {
                                tabularResults.push({ key, success_count: null, failure_count: null })
                            } else if (metricType === InsightType.TRENDS) {
                                tabularResults.push({ key, count: null, exposure: null, absolute_exposure: null })
                            }
                        }
                    }

                    return tabularResults
                },
        ],
        sortedWinProbabilities: [
            (s) => [s.legacyPrimaryMetricsResults, s.experiment],
            (
                legacyPrimaryMetricsResults: (
                    | CachedLegacyExperimentQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                    | CachedExperimentTrendsQueryResponse
                    | null
                )[],
                experiment: Experiment | null
            ) =>
                (metricIdentifier: number | string = 0) => {
                    if (!experiment) {
                        return []
                    }
                    let index: number
                    if (typeof metricIdentifier === 'string') {
                        index = experiment.metrics.findIndex((m) => m.uuid === metricIdentifier)
                        if (index === -1) {
                            return []
                        }
                    } else {
                        index = metricIdentifier
                    }

                    const result = legacyPrimaryMetricsResults?.[index]

                    if (!result) {
                        return []
                    }

                    return Object.keys(result.probability)
                        .map((key) => ({
                            key,
                            winProbability: result.probability[key],
                            conversionRate: legacyConversionRateForVariant(result, key),
                        }))
                        .sort((a, b) => b.winProbability - a.winProbability)
                },
        ],
        funnelResultsPersonsTotal: [
            (s) => [s.experiment, s.legacyPrimaryMetricsResults, s.getInsightType],
            (
                experiment,
                legacyPrimaryMetricsResults: (
                    | CachedLegacyExperimentQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                    | CachedExperimentTrendsQueryResponse
                    | null
                )[],
                getInsightType
            ) =>
                (metricIdentifier: number | string = 0): number => {
                    if (!experiment) {
                        return 0
                    }
                    let index: number
                    if (typeof metricIdentifier === 'string') {
                        index = experiment.metrics.findIndex((m) => m.uuid === metricIdentifier)
                        if (index === -1) {
                            return 0
                        }
                    } else {
                        index = metricIdentifier
                    }

                    const result = legacyPrimaryMetricsResults?.[index]

                    if (getInsightType(experiment.metrics[index]) !== InsightType.FUNNELS || !result) {
                        return 0
                    }

                    let sum = 0
                    result.insight.forEach((variantResult) => {
                        if (variantResult[0]?.count) {
                            sum += variantResult[0].count
                        }
                    })
                    return sum
                },
        ],
        actualRunningTime: [
            (s) => [s.experiment],
            (experiment: Experiment | null): number => {
                if (!experiment || !experiment.start_date) {
                    return 0
                }

                if (experiment.end_date) {
                    return dayjs(experiment.end_date).diff(experiment.start_date, 'day')
                }

                return dayjs().diff(experiment.start_date, 'day')
            },
        ],
        isSingleVariantShipped: [
            (s) => [s.experiment],
            (experiment: Experiment | null): boolean => {
                if (!experiment) {
                    return false
                }
                return isSingleVariantShipped(experiment)
            },
        ],
        shippedVariantKey: [
            (s) => [s.experiment],
            (experiment: Experiment | null): string | null => {
                if (!experiment) {
                    return null
                }
                return getShippedVariantKey(experiment)
            },
        ],
        firstPrimaryMetric: [
            (s) => [s.experiment],
            (experiment: Experiment | null): ExperimentTrendsQuery | ExperimentFunnelsQuery | undefined => {
                if (!experiment || !experiment.metrics.length) {
                    return undefined
                }
                return experiment.metrics[0] as ExperimentTrendsQuery | ExperimentFunnelsQuery
            },
        ],
        hasMinimumExposureForResults: [
            () => [],
            (): boolean => {
                // Legacy experiments always return true since they don't use the new exposure system
                return true
            },
        ],
    }),
])
