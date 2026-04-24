import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { runWithLimit } from 'scenes/dashboard/dashboardUtils'
import { isLegacyExperimentQuery, isLegacySharedMetric } from 'scenes/experiments/utils'
import { teamLogic } from 'scenes/teamLogic'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import api from '~/lib/api'
import { QUERY_TIMEOUT_ERROR_MESSAGE, performQuery } from '~/queries/query'
import {
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentTrendsQueryResponse,
    CachedLegacyExperimentQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { Experiment } from '~/types'

import { modalsLogic } from '../modalsLogic'
import type { legacyExperimentLogicType } from './legacyExperimentLogicType'

export interface LegacyExperimentLogicProps {
    experiment: Experiment
    tabId: string
}

export type LegacyExperimentTriggeredBy = 'page_load' | 'manual' | 'auto_refresh' | 'config_change'

/**
 * Validates that an experiment only contains legacy metrics.
 * This is a defensive check to ensure the legacy logic doesn't attempt
 * to load modern ExperimentMetric queries.
 *
 * @returns Object with isValid boolean and error message if invalid
 */
function validateLegacyExperiment(experiment: Experiment): { isValid: boolean; error?: string } {
    // Check all direct metrics
    const nonLegacyMetrics = [...experiment.metrics, ...experiment.metrics_secondary].filter(
        (metric) => !isLegacyExperimentQuery(metric)
    )

    if (nonLegacyMetrics.length > 0) {
        return {
            isValid: false,
            error: `Found ${nonLegacyMetrics.length} non-legacy metric(s) in experiment. Legacy logic only supports ExperimentTrendsQuery and ExperimentFunnelsQuery.`,
        }
    }

    // Check saved metrics
    const nonLegacySavedMetrics = experiment.saved_metrics.filter((sm) => !isLegacySharedMetric(sm))

    if (nonLegacySavedMetrics.length > 0) {
        return {
            isValid: false,
            error: `Found ${nonLegacySavedMetrics.length} non-legacy saved metric(s) in experiment. Legacy logic only supports ExperimentTrendsQuery and ExperimentFunnelsQuery.`,
        }
    }

    return { isValid: true }
}

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

interface LegacyMetricLoadingConfig {
    metrics: any[]
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

interface LegacyMetricLoadingSummary {
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

// Max concurrent metric queries to avoid overwhelming the celery queue's
// per-team concurrency limit (10). Using runWithLimit instead of Promise.all
// prevents mass rejections and retry churn when experiments have many metrics.
const METRIC_QUERY_CONCURRENCY_LIMIT = 10

const loadLegacyMetrics = async ({
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
}: LegacyMetricLoadingConfig): Promise<LegacyMetricLoadingSummary> => {
    const legacyResults: (
        | CachedLegacyExperimentQueryResponse
        | CachedExperimentTrendsQueryResponse
        | CachedExperimentFunnelsQueryResponse
        | null
    )[] = []

    const currentErrors = new Array(metrics.length).fill(null)

    let successfulCount = 0
    let erroredCount = 0
    let cachedCount = 0

    // Build tasks in display order so higher-priority metrics get dispatched first,
    // but each task writes to its original index so the UI stays consistent.
    const displayOrder = getDisplayOrderedIndices(metrics, orderedUuids)

    const tasks = displayOrder.map((originalIndex) => {
        const metric = metrics[originalIndex]
        return async (): Promise<void> => {
            let response: any = null
            const startTime = performance.now()
            const metricIndex = metricIndexOffset + originalIndex
            const metricKind = metric.kind || 'unknown'

            try {
                let queryWithExperimentId
                if (metric.kind === NodeKind.ExperimentMetric) {
                    queryWithExperimentId = {
                        kind: NodeKind.ExperimentQuery,
                        metric: metric,
                        experiment_id: experimentId,
                    }
                } else {
                    queryWithExperimentId = {
                        ...metric,
                        experiment_id: experimentId,
                    }
                }
                response = await performQuery(
                    setLatestVersionsOnQuery(queryWithExperimentId),
                    undefined,
                    refresh ? 'force_async' : 'async'
                )

                const durationMs = Math.round(performance.now() - startTime)
                const isCached = !!response?.is_cached

                // All responses in legacy experiments are legacy format
                // Add fakeInsightId for tracking
                legacyResults[originalIndex] = {
                    ...response,
                    fakeInsightId: Math.random().toString(36).substring(2, 15),
                } as (
                    | CachedLegacyExperimentQueryResponse
                    | CachedExperimentTrendsQueryResponse
                    | CachedExperimentFunnelsQueryResponse
                ) & {
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
                        execution_mode: 'async',
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

/**
 * @deprecated Legacy experiment logic for read-only legacy experiments.
 *
 * This logic handles ONLY metrics results loading for experiments that use
 * ExperimentTrendsQuery and ExperimentFunnelsQuery (legacy format).
 *
 * Key principles:
 * - Receives experiment as prop (no duplicate loading)
 * - Mostly read-only: legacy experiments can be archived, ended or finished, but not edited
 * - Loads and metrics results
 * - Legacy experiments are frozen/read-only, so no auto-refresh or notifications
 *
 * New experiments should use the modern experimentLogic.tsx instead.
 */
export const legacyExperimentLogic = kea<legacyExperimentLogicType>([
    props({} as LegacyExperimentLogicProps),
    key((props) => {
        const baseKey = props.experiment.id ?? 'new'
        return `${baseKey}${props.tabId ? `-${props.tabId}` : ''}-legacy`
    }),
    path((key) => ['scenes', 'experiments', 'legacy', 'legacyExperimentLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId', 'currentProjectId']],
        actions: [modalsLogic, ['closeFinishExperimentModal']],
    })),
    actions({
        // Experiment mutations
        archiveExperiment: true,
        endExperiment: true,
        endExperimentWithoutShipping: true,
        finishExperiment: ({ selectedVariantKey }: { selectedVariantKey: string }) => ({ selectedVariantKey }),
        setExperiment: (update: Partial<Experiment>) => ({ update }),
        restoreUnmodifiedExperiment: true,

        // Metrics results loading
        refreshExperimentResults: (forceRefresh?: boolean, triggeredBy?: LegacyExperimentTriggeredBy) => ({
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
        setLegacySecondaryMetricsResults: (
            results: (
                | CachedLegacyExperimentQueryResponse
                | CachedExperimentTrendsQueryResponse
                | CachedExperimentFunnelsQueryResponse
                | null
            )[]
        ) => ({ results }),
        loadSecondaryMetricsResults: (refresh?: boolean, refreshId?: string) => ({ refresh, refreshId }),
        setSecondaryMetricsResultsErrors: (errors: any[]) => ({ errors }),
        setSecondaryMetricsResultsLoading: (loading: boolean) => ({ loading }),
    }),
    reducers(({ props }) => ({
        experiment: [
            props.experiment,
            {
                setExperiment: (state, { update }) => ({ ...state, ...update }),
            },
        ],
        unmodifiedExperiment: [
            props.experiment as Experiment | null,
            {
                setExperiment: (state) => state, // Preserve unmodified version
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
            },
        ],
        primaryMetricsResultsLoading: [
            false,
            {
                loadPrimaryMetricsResults: () => true,
                setPrimaryMetricsResultsLoading: (_, { loading }) => loading,
            },
        ],
        primaryMetricsResultsErrors: [
            [] as any[],
            {
                setPrimaryMetricsResultsErrors: (_, { errors }) => errors,
                loadPrimaryMetricsResults: () => [],
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
            },
        ],
        secondaryMetricsResultsLoading: [
            false,
            {
                loadSecondaryMetricsResults: () => true,
                setSecondaryMetricsResultsLoading: (_, { loading }) => loading,
            },
        ],
        secondaryMetricsResultsErrors: [
            [] as any[],
            {
                setSecondaryMetricsResultsErrors: (_, { errors }) => errors,
                loadSecondaryMetricsResults: () => [],
            },
        ],
    })),
    selectors({
        experimentId: [(s) => [s.experiment], (experiment) => experiment.id],
    }),
    listeners(({ values, actions }) => ({
        afterMount: () => {
            const experiment = values.experiment

            // Defensive check: Verify all metrics are legacy on mount
            const validation = validateLegacyExperiment(experiment)
            if (!validation.isValid) {
                lemonToast.error(
                    `Cannot load metrics: ${validation.error} This experiment should use the modern experiment view.`
                )
                return
            }
        },
        archiveExperiment: async () => {
            try {
                const response: Experiment = await api.create(
                    `/api/projects/${values.currentProjectId}/experiments/${values.experimentId}/archive`
                )
                actions.setExperiment(response)
                refreshTreeItem('experiment', String(values.experimentId))
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to archive experiment')
            }
        },
        endExperiment: async () => {
            try {
                const response: Experiment = await api.create(
                    `/api/projects/${values.currentProjectId}/experiments/${values.experimentId}/end`,
                    {
                        conclusion: values.experiment.conclusion,
                        conclusion_comment: values.experiment.conclusion_comment,
                    }
                )
                actions.setExperiment(response)
                refreshTreeItem('experiment', String(values.experimentId))
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to end experiment')
            }
        },
        endExperimentWithoutShipping: async () => {
            actions.endExperiment()
            actions.closeFinishExperimentModal()
            lemonToast.success('Experiment ended successfully')
        },
        finishExperiment: async ({ selectedVariantKey }) => {
            try {
                const response: Experiment = await api.create(
                    `/api/projects/${values.currentProjectId}/experiments/${values.experimentId}/ship_variant`,
                    {
                        variant_key: selectedVariantKey,
                        conclusion: values.experiment.conclusion,
                        conclusion_comment: values.experiment.conclusion_comment,
                    }
                )
                actions.setExperiment(response)
                refreshTreeItem('experiment', String(values.experimentId))
                actions.closeFinishExperimentModal()
                lemonToast.success('Experiment ended. The selected variant has been rolled out to all users.')
            } catch (error: any) {
                actions.closeFinishExperimentModal()
                lemonToast.error(error.detail || 'Failed to ship variant')
            }
        },
        restoreUnmodifiedExperiment: () => {
            if (values.unmodifiedExperiment) {
                actions.setExperiment(values.unmodifiedExperiment)
            }
        },
        refreshExperimentResults: async ({ forceRefresh }) => {
            // Generate a unique refresh ID for tracking
            const refreshId = generateRefreshId()

            // Always refresh both primary and secondary metrics
            actions.loadPrimaryMetricsResults(forceRefresh, refreshId)
            actions.loadSecondaryMetricsResults(forceRefresh, refreshId)
        },
        loadPrimaryMetricsResults: async ({ refresh, refreshId }) => {
            const experiment = values.experiment
            const metrics = [...experiment.metrics]
            const savedMetricsPrimary = experiment.saved_metrics
                .filter((sm) => sm.metadata.type === 'primary')
                .map((sm) => sm.query)

            const allMetrics = [...metrics, ...savedMetricsPrimary]

            if (allMetrics.length === 0) {
                actions.setPrimaryMetricsResultsLoading(false)
                return
            }

            try {
                await loadLegacyMetrics({
                    metrics: allMetrics,
                    experimentId: experiment.id,
                    refresh,
                    teamId: values.currentTeamId,
                    refreshId: refreshId || generateRefreshId(),
                    isPrimary: true,
                    isRetry: false,
                    metricIndexOffset: 0,
                    orderedUuids: experiment.primary_metrics_ordered_uuids,
                    onSetLegacyResults: (results) => actions.setLegacyPrimaryMetricsResults(results),
                    onSetErrors: (errors) => actions.setPrimaryMetricsResultsErrors(errors),
                })
            } finally {
                actions.setPrimaryMetricsResultsLoading(false)
            }
        },
        loadSecondaryMetricsResults: async ({ refresh, refreshId }) => {
            const experiment = values.experiment
            const metrics = [...experiment.metrics_secondary]
            const savedMetricsSecondary = experiment.saved_metrics
                .filter((sm) => sm.metadata.type === 'secondary')
                .map((sm) => sm.query)

            const allMetrics = [...metrics, ...savedMetricsSecondary]

            if (allMetrics.length === 0) {
                actions.setSecondaryMetricsResultsLoading(false)
                return
            }

            const savedMetricsPrimary = experiment.saved_metrics.filter((sm) => sm.metadata.type === 'primary')

            try {
                await loadLegacyMetrics({
                    metrics: allMetrics,
                    experimentId: experiment.id,
                    refresh,
                    teamId: values.currentTeamId,
                    refreshId: refreshId || generateRefreshId(),
                    isPrimary: false,
                    isRetry: false,
                    metricIndexOffset: experiment.metrics.length + savedMetricsPrimary.length,
                    orderedUuids: experiment.secondary_metrics_ordered_uuids,
                    onSetLegacyResults: (results) => actions.setLegacySecondaryMetricsResults(results),
                    onSetErrors: (errors) => actions.setSecondaryMetricsResultsErrors(errors),
                })
            } finally {
                actions.setSecondaryMetricsResultsLoading(false)
            }
        },
    })),
])
