import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { projectLogic } from 'scenes/projectLogic'

import type { Breakdown, CachedNewExperimentQueryResponse, ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import {
    experimentsMetricsRecalculationCreate,
    experimentsMetricsRecalculationLatestRetrieve,
    experimentsMetricsRecalculationRetrieve,
} from 'products/experiments/frontend/generated/api'
import type { ExperimentMetricsRecalculationApi } from 'products/experiments/frontend/generated/api.schemas'

import type { experimentMetricsLogicType } from './experimentMetricsLogicType'
import { hasEnded, isLaunched } from './experimentsLogic'

type ExperimentSavedMetric = {
    metadata: {
        type: 'primary' | 'secondary'
        breakdowns?: Breakdown[]
    }
    query: ExperimentMetric
}

/**
 * This logic can only handle state when an experiment is present.
 */
export interface ExperimentMetricsLogicProps {
    experiment: Experiment
}

const RECALCULATION_POLL_INTERVAL_MS = 2000
const RECALCULATION_STALE_AFTER_HOURS = 24
const MAX_POLL_RETRIES = 5

export const RECALCULATION_STATUSES = {
    pending: 'pending',
    in_progress: 'in_progress',
    completed: 'completed',
    failed: 'failed',
} as const

export type RecalculationStatuses = (typeof RECALCULATION_STATUSES)[keyof typeof RECALCULATION_STATUSES]

const isRecalculationStale = (recalculation: ExperimentMetricsRecalculationApi): boolean => {
    if (!recalculation.completed_at) {
        return false
    }
    return dayjs().diff(dayjs(recalculation.completed_at), 'hours') >= RECALCULATION_STALE_AFTER_HOURS
}

/**
 * transform shared metrics into experiment metrics.
 */
const sharedMetricsToExperimentMetrics = (
    sharedMetrics: ExperimentSavedMetric[],
    type: 'primary' | 'secondary'
): ExperimentMetric[] =>
    sharedMetrics
        .filter(({ metadata }) => metadata.type === type)
        .map(({ query, metadata }) => ({
            ...query,
            breakdownFilter: {
                ...query?.breakdownFilter,
                breakdowns: metadata?.breakdowns || [],
            },
        }))

// One metric type's metrics (inline + shared) in the order results are positionally mapped against.
const metricsInOrder = (experiment: Experiment, type: 'primary' | 'secondary'): ExperimentMetric[] => {
    const sharedMetrics = sharedMetricsToExperimentMetrics(experiment.saved_metrics as ExperimentSavedMetric[], type)
    const inline = (type === 'primary' ? experiment.metrics : experiment.metrics_secondary) || []
    return [...(inline as ExperimentMetric[]), ...sharedMetrics]
}

type MetricErrorState = { detail: string } | null
type ResolveByUuid<T> = (uuid: string) => T

/**
 * One value per metric, in `metricsInOrder` order. Curried: bind (experiment, type) once, then feed a
 * per-uuid resolver, the only thing that differs between results and errors.
 */
const alignByMetricPosition =
    (experiment: Experiment, type: 'primary' | 'secondary') =>
    <T>(resolve: ResolveByUuid<T>): T[] =>
        metricsInOrder(experiment, type).map((metric) => resolve(metric.uuid as string))

// Resolver: a polled metric's computed result, or undefined if the run hasn't produced one yet.
const resolveResultByUuid = (
    polledResults: readonly { metric_uuid: string; result: unknown }[] | undefined
): ResolveByUuid<CachedNewExperimentQueryResponse> => {
    const resultByUuid = new Map((polledResults ?? []).map((r) => [r.metric_uuid, r.result]))
    return (uuid) => resultByUuid.get(uuid) as CachedNewExperimentQueryResponse
}

/**
 * Resolver: a metric's failure as `{ detail }` (the MetricErrorState shape), or null. `metric_errors`
 * wins (it covers FAILED rows AND discovery-step failures absent from `results`), falling back to a
 * failed row's error_message.
 */
const resolveErrorByUuid = (recalculation: ExperimentMetricsRecalculationApi): ResolveByUuid<MetricErrorState> => {
    const metricErrors = (recalculation.metric_errors as Record<string, { message?: string }> | null) ?? {}
    const failedResultMessageByUuid = new Map(
        (recalculation.results ?? [])
            .filter((r) => r.status === 'failed' && r.error_message)
            .map((r) => [r.metric_uuid, r.error_message as string])
    )
    return (uuid) => {
        const message = metricErrors[uuid]?.message ?? failedResultMessageByUuid.get(uuid)
        return message ? { detail: message } : null
    }
}

export const experimentMetricsLogic = kea<experimentMetricsLogicType>([
    props({} as ExperimentMetricsLogicProps),
    key((props) => props.experiment.id),
    path((key) => ['scenes', 'experiment', 'experimentMetricsLogic', String(key)]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], featureFlagLogic, ['featureFlags']],
        actions: [eventUsageLogic, ['reportExperimentMetricRecalculation']],
    })),
    actions({
        setCurrentRecalculation: (recalculation: ExperimentMetricsRecalculationApi | null) => ({ recalculation }),
        loadLatestRecalculation: true,
        triggerRecalculation: true,
        pollRecalculation: (recalculationId: string) => ({ recalculationId }),
        setPrimaryMetricsResults: (results: CachedNewExperimentQueryResponse[]) => ({ results }),
        setSecondaryMetricsResults: (results: CachedNewExperimentQueryResponse[]) => ({ results }),
        setPrimaryMetricsResultsErrors: (errors: (unknown | null)[]) => ({ errors }),
        setSecondaryMetricsResultsErrors: (errors: (unknown | null)[]) => ({ errors }),
        setRecalculationLoading: (loading: boolean) => ({ loading }),
    }),
    reducers({
        currentRecalculation: [
            null as ExperimentMetricsRecalculationApi | null,
            {
                setCurrentRecalculation: (_, { recalculation }) => recalculation,
            },
        ],
        recalculationLoading: [
            false,
            {
                setRecalculationLoading: (_, { loading }) => loading,
                loadLatestRecalculation: () => true,
                setCurrentRecalculation: () => false,
            },
        ],
        primaryMetricsResults: [
            [] as CachedNewExperimentQueryResponse[],
            {
                setPrimaryMetricsResults: (_, { results }) => results,
            },
        ],
        secondaryMetricsResults: [
            [] as CachedNewExperimentQueryResponse[],
            {
                setSecondaryMetricsResults: (_, { results }) => results,
            },
        ],
        primaryMetricsResultsErrors: [
            [] as (unknown | null)[],
            {
                setPrimaryMetricsResultsErrors: (_, { errors }) => errors,
            },
        ],
        secondaryMetricsResultsErrors: [
            [] as (unknown | null)[],
            {
                setSecondaryMetricsResultsErrors: (_, { errors }) => errors,
            },
        ],
    }),
    selectors({
        // True while a recalculation is being fetched or is still running.
        isRecalculating: [
            (s) => [s.recalculationLoading, s.currentRecalculation],
            (recalculationLoading, recalculation): boolean =>
                recalculationLoading ||
                recalculation?.status === RECALCULATION_STATUSES.pending ||
                recalculation?.status === RECALCULATION_STATUSES.in_progress,
        ],
        recalculationProgress: [
            (s) => [s.currentRecalculation],
            (recalc): { completed: number; total: number } => ({
                completed: recalc?.completed_metrics ?? 0,
                total: recalc?.total_metrics ?? 0,
            }),
        ],
        lastRefresh: [(s) => [s.currentRecalculation], (recalc): string | null => recalc?.completed_at ?? null],
    }),
    listeners(({ actions, values, props, cache }) => {
        const flagEnabled = (): boolean => !!values.featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]

        /**
         * Recalculations only make sense for a running experiment: a draft has no results to fetch, and a
         * stopped one is frozen. Gates both the latest-fetch and triggering a new run.
         */
        const experimentIsRunning = (): boolean => isLaunched(props.experiment) && !hasEnded(props.experiment)

        /**
         * some local helpers for the listeners closure
         */

        /**
         * extracts project id and experiment id from values and props.
         */
        const ids = (): { projectId: number; experimentId: number } | null => {
            const projectId = values.currentProjectId
            const experimentId = props.experiment.id
            if (!projectId || typeof experimentId !== 'number') {
                return null
            }
            return { projectId, experimentId }
        }

        /**
         * Emit the terminal analytics event for a recalc run. Reads duration_ms / poll_count off the cache
         * fields set on trigger; both are 0 on a terminal-on-create run because no poll ever happened.
         */
        const emitTerminalEvent = (recalculation: ExperimentMetricsRecalculationApi): void => {
            const startMs = cache.recalcStartMs ?? Date.now()
            actions.reportExperimentMetricRecalculation(
                recalculation.status === RECALCULATION_STATUSES.completed ? 'completed' : 'failed',
                {
                    experiment_id: props.experiment.id as number,
                    recalculation_id: recalculation.id,
                    total_metrics: recalculation.total_metrics,
                    succeeded: recalculation.completed_metrics,
                    failed: recalculation.failed_metrics,
                    duration_ms: Date.now() - startMs,
                    poll_count: cache.pollCount ?? 0,
                }
            )
        }

        /**
         * apply per-metric results and errors by setting primary and secondary metric results and errors.
         * Partial failures will load the metrics that succeeded, and failed metrics get a nice error view.
         */
        const applyResults = (recalculation: ExperimentMetricsRecalculationApi): void => {
            const resultFor = resolveResultByUuid(recalculation.results)
            const errorFor = resolveErrorByUuid(recalculation)

            const alignPrimary = alignByMetricPosition(props.experiment, 'primary')
            const alignSecondary = alignByMetricPosition(props.experiment, 'secondary')

            actions.setPrimaryMetricsResults(alignPrimary(resultFor))
            actions.setSecondaryMetricsResults(alignSecondary(resultFor))
            actions.setPrimaryMetricsResultsErrors(alignPrimary(errorFor))
            actions.setSecondaryMetricsResultsErrors(alignSecondary(errorFor))
        }

        return {
            loadLatestRecalculation: async () => {
                /**
                 * bail if feature not enabled. Clear recalculation loading state
                 */
                if (!flagEnabled()) {
                    actions.setRecalculationLoading(false)
                    return
                }
                // Don't fetch for draft or stopped experiments — there's nothing to recalculate.
                if (!experimentIsRunning()) {
                    actions.setRecalculationLoading(false)
                    return
                }
                /**
                 * guard against invalid project or experiment. bail and clear recalculation
                 * loading state
                 */
                const resolvedIds = ids()
                if (!resolvedIds) {
                    actions.setRecalculationLoading(false)
                    return
                }

                try {
                    const { projectId, experimentId } = resolvedIds
                    /**
                     * retrieve the latest complete recalculation so we always show results, even if stale.
                     * store it in state and apply the results.
                     */
                    const recalculation = await experimentsMetricsRecalculationLatestRetrieve(
                        String(projectId),
                        experimentId
                    )
                    actions.setCurrentRecalculation(recalculation)
                    applyResults(recalculation)

                    /**
                     * if the recalculation resutls are stale, trigger a new recalculation
                     * without hiding the existing resutls.
                     */
                    if (isRecalculationStale(recalculation)) {
                        actions.triggerRecalculation()
                    }
                } catch (error: any) {
                    if (error?.status === 404) {
                        /**
                         * if there are no completed recalculations, kick off a new one.
                         * this should only run on page loads, so no need to load exposures.
                         */
                        actions.triggerRecalculation()
                        return
                    }

                    lemonToast.error('Failed to load latest recalculation')
                } finally {
                    actions.setRecalculationLoading(false)
                }
            },
            triggerRecalculation: async () => {
                /**
                 * bail if feature not enabled
                 */
                if (!flagEnabled()) {
                    return
                }
                /**
                 * Don't recalculate draft or stopped experiments; a config-change edit on either shouldn't
                 * kick off a run.
                 */
                if (!experimentIsRunning()) {
                    return
                }
                /**
                 * guard against invalid project or experiment. bail and clear recalculation
                 * loading state
                 */
                const resolvedIds = ids()
                if (!resolvedIds) {
                    return
                }
                try {
                    const { projectId, experimentId } = resolvedIds
                    // 201 with a new pending run, or 200 with the already-active one. No results yet.
                    // Create a recalculation workflow. 201: a new run. 200: one is already running, poll it.
                    const recalculation = await experimentsMetricsRecalculationCreate(String(projectId), experimentId, {
                        trigger: 'manual',
                    })

                    /**
                     * Mark the active run. A terminal-on-create run (below) applies results without
                     * dispatching pollRecalculation, so breakpoint can't abort an older poll; pollRecalculation
                     * re-checks this id after its fetch and bails if a newer run took over.
                     */
                    cache.activeRecalculationId = recalculation.id
                    /**
                     * Lifecycle clock + poll count for the terminal-state analytics event. Reset on every
                     * trigger so duration_ms / poll_count are anchored to THIS run.
                     */
                    cache.recalcStartMs = Date.now()
                    cache.pollCount = 0
                    cache.pollRetryCount = 0
                    actions.setCurrentRecalculation(recalculation)
                    actions.reportExperimentMetricRecalculation('triggered', {
                        experiment_id: experimentId,
                        recalculation_id: recalculation.id,
                        trigger: 'manual',
                        is_existing: recalculation.is_existing,
                    })

                    if (
                        recalculation.status === RECALCULATION_STATUSES.completed ||
                        recalculation.status === RECALCULATION_STATUSES.failed
                    ) {
                        /**
                         * Create can return an already-terminal run (e.g. a completed one finished between
                         * request and response). Load its results directly rather than polling.
                         */
                        applyResults(recalculation)
                        emitTerminalEvent(recalculation)
                    } else {
                        actions.pollRecalculation(recalculation.id)
                    }
                } catch (error: any) {
                    lemonToast.error(error?.detail || 'Failed to trigger metrics recalculation')
                }
            },
            /**
             * Polls one run to terminal status, re-arming one tick at a time rather than looping in place.
             * `breakpoint` is kea's cancellation primitive: `await breakpoint(ms)` paces the poll and throws
             * if pollRecalculation re-fires or the logic unmounts; `breakpoint()` re-checks without delaying.
             * So a newer poll auto-cancels this one's in-flight breakpoint before it can write stale results:
             * free poll-vs-poll supersession, no interval to clear. The gap: a terminal-on-create run applies
             * results without dispatching pollRecalculation, so cache.activeRecalculationId covers that case.
             */
            pollRecalculation: async ({ recalculationId }, breakpoint) => {
                if (!flagEnabled()) {
                    return
                }
                const resolvedIds = ids()
                if (!resolvedIds) {
                    return
                }
                const { projectId, experimentId } = resolvedIds
                // First tick of a new run (the active id changed): reset the retry streak so a prior run that
                // exhausted its retries doesn't leave the counter at the cap for this one.
                if (cache.activeRecalculationId !== recalculationId) {
                    cache.pollRetryCount = 0
                }
                cache.activeRecalculationId = recalculationId

                // Pace this tick; aborts here if a newer poll superseded us or the logic unmounted.
                await breakpoint(RECALCULATION_POLL_INTERVAL_MS)

                let recalculation: ExperimentMetricsRecalculationApi
                try {
                    recalculation = await experimentsMetricsRecalculationRetrieve(
                        String(projectId),
                        experimentId,
                        recalculationId
                    )
                } catch {
                    /**
                     * Retry on transient errors, but give up after MAX_POLL_RETRIES consecutive failures so a
                     * persistently failing endpoint can't poll forever.
                     */
                    cache.pollRetryCount = (cache.pollRetryCount ?? 0) + 1
                    if (cache.pollRetryCount >= MAX_POLL_RETRIES) {
                        lemonToast.error('Failed to load recalculation results. Please reload to try again.')
                        return
                    }
                    actions.pollRecalculation(recalculationId)
                    return
                }
                // Healthy response; reset the retry streak so an earlier blip doesn't count against later ticks.
                cache.pollRetryCount = 0
                // A newer poll may have started while the request was in flight; abort before writing results.
                breakpoint()
                /**
                 * breakpoint covers a newer POLL; this covers a newer terminal-on-create run that applied
                 * results directly without dispatching pollRecalculation (so breakpoint never fired for us).
                 */
                if (cache.activeRecalculationId !== recalculationId) {
                    return
                }

                /**
                 * Count only polls that pass the supersession check so the analytics event reflects the work
                 * THIS run actually paid for; superseded ticks would otherwise inflate the number.
                 */
                cache.pollCount = (cache.pollCount ?? 0) + 1

                actions.setCurrentRecalculation(recalculation)

                if (
                    recalculation.status === RECALCULATION_STATUSES.pending ||
                    recalculation.status === RECALCULATION_STATUSES.in_progress
                ) {
                    actions.pollRecalculation(recalculationId)
                    return
                }

                // Successful metrics load, failed metrics surface their error in-row.
                applyResults(recalculation)
                emitTerminalEvent(recalculation)
                if (recalculation.failed_metrics > 0) {
                    lemonToast.error(
                        `${recalculation.failed_metrics} of ${recalculation.total_metrics} metrics failed to load`
                    )
                }
            },
        }
    }),
    afterMount(({ actions, values, cache }) => {
        // Fetch the latest completed recalculation on mount; the listener no-ops when the flag is off.
        actions.loadLatestRecalculation()

        /**
         * On tab visible, re-fetch the latest only when nothing is loaded: refetching would overwrite a
         * displayed failure state with the last completed run.
         */
        cache.disposables.add(
            () => {
                const handler = (): void => {
                    if (document.visibilityState === 'visible' && !values.currentRecalculation) {
                        actions.loadLatestRecalculation()
                    }
                }
                document.addEventListener('visibilitychange', handler)
                return () => document.removeEventListener('visibilitychange', handler)
            },
            'recalculationVisibility',
            { pauseOnPageHidden: false }
        )
    }),
])
