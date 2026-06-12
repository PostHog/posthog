import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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

const buildRecalculationResultsByPosition = (
    experiment: Experiment,
    polledResults: readonly { metric_uuid: string; result: unknown }[] | undefined,
    type: 'primary' | 'secondary'
): CachedNewExperimentQueryResponse[] => {
    if (!polledResults) {
        return []
    }
    const resultByUuid = new Map(polledResults.map((r) => [r.metric_uuid, r.result]))
    return metricsInOrder(experiment, type).map(
        (metric) => resultByUuid.get(metric.uuid as string) as CachedNewExperimentQueryResponse
    )
}

// Errors positionally aligned with the results array: a metric that failed gets a `{ detail }` error
// (the shape MetricErrorState renders), everything else `null`. `metric_errors` is the authoritative
// per-metric failure map — it covers both FAILED result rows AND discovery-step failures that never
// produced a result row (the latter are absent from `results`), so drive the errors off it.
const buildRecalculationErrorsByPosition = (
    experiment: Experiment,
    recalculation: ExperimentMetricsRecalculationApi,
    type: 'primary' | 'secondary'
): (unknown | null)[] => {
    const metricErrors = (recalculation.metric_errors as Record<string, { message?: string }> | null) || {}
    // Result-row error_message as a fallback for any failed result not present in metric_errors.
    const resultErrorByUuid = new Map<string, string>()
    for (const result of recalculation.results || []) {
        if (result.status === 'failed' && result.error_message) {
            resultErrorByUuid.set(result.metric_uuid, result.error_message)
        }
    }

    return metricsInOrder(experiment, type).map((metric) => {
        const uuid = metric.uuid as string
        const message = metricErrors[uuid]?.message ?? resultErrorByUuid.get(uuid)
        return message ? { detail: message } : null
    })
}

export const experimentMetricsLogic = kea<experimentMetricsLogicType>([
    props({} as ExperimentMetricsLogicProps),
    key((props) => props.experiment.id),
    path((key) => ['scenes', 'experiment', 'experimentMetricsLogic', String(key)]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], featureFlagLogic, ['featureFlags']],
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
         * apply per-metric results and errors by setting primary and secondary metric results and errors.
         * Partial failures will load the metrics that succeeded, and failed metrics get a nice error view.
         */
        const applyResults = (recalculation: ExperimentMetricsRecalculationApi): void => {
            actions.setPrimaryMetricsResults(
                buildRecalculationResultsByPosition(props.experiment, recalculation.results, 'primary')
            )
            actions.setSecondaryMetricsResults(
                buildRecalculationResultsByPosition(props.experiment, recalculation.results, 'secondary')
            )
            actions.setPrimaryMetricsResultsErrors(
                buildRecalculationErrorsByPosition(props.experiment, recalculation, 'primary')
            )
            actions.setSecondaryMetricsResultsErrors(
                buildRecalculationErrorsByPosition(props.experiment, recalculation, 'secondary')
            )
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
                    /**
                     * create a new recalculation workflow. If 200, there's already a workflow running, so we poll for it.
                     * If 201, we started a new workflow run.
                     */
                    const recalculation = await experimentsMetricsRecalculationCreate(String(projectId), experimentId, {
                        trigger: 'manual',
                    })

                    // Mark this as the active run. breakpoint handles poll-vs-poll supersession, but a
                    // terminal-on-create run (below) applies results without dispatching pollRecalculation,
                    // so it can't abort an older run's in-flight poll that way. pollRecalculation re-checks
                    // this id after its fetch and bails if a newer run has taken over.
                    cache.activeRecalculationId = recalculation.id
                    actions.setCurrentRecalculation(recalculation)

                    if (
                        recalculation.status === RECALCULATION_STATUSES.completed ||
                        recalculation.status === RECALCULATION_STATUSES.failed
                    ) {
                        // Create can return an already-terminal run (e.g. a completed one finished between
                        // request and response). Load its results directly rather than polling.
                        applyResults(recalculation)
                    } else {
                        actions.pollRecalculation(recalculation.id)
                    }
                } catch (error: any) {
                    lemonToast.error(error?.detail || 'Failed to trigger metrics recalculation')
                }
            },
            // Polls one recalculation run until it reaches a terminal status, re-arming itself one tick at
            // a time (see `actions.pollRecalculation(recalculationId)` below) rather than looping in place.
            //
            // `breakpoint` is kea's listener-cancellation primitive. It does two jobs here:
            //   - `await breakpoint(ms)` pauses for `ms` AND throws (silently aborting this listener run) if
            //     pollRecalculation is dispatched again or the logic unmounts during the wait — so it doubles
            //     as our poll interval.
            //   - `breakpoint()` (no args) re-checks the same condition after an await without delaying.
            //
            // Why this is the right tool: when a NEWER recalculation supersedes this one by dispatching
            // pollRecalculation again, the in-flight breakpoint of the OLD run throws before it can write
            // stale results. kea gives us that poll-vs-poll supersession guard for free — no interval to
            // clear on unmount. The one case breakpoint can't see is a newer terminal-on-create run, which
            // applies results without dispatching pollRecalculation; cache.activeRecalculationId covers it.
            pollRecalculation: async ({ recalculationId }, breakpoint) => {
                if (!flagEnabled()) {
                    return
                }
                const resolvedIds = ids()
                if (!resolvedIds) {
                    return
                }
                const { projectId, experimentId } = resolvedIds
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
                    // Transient error. Try again on the next tick.
                    actions.pollRecalculation(recalculationId)
                    return
                }
                // A newer poll may have started while the request was in flight; abort before writing results.
                breakpoint()
                // breakpoint covers a newer POLL; this covers a newer terminal-on-create run that applied
                // results directly without dispatching pollRecalculation (so breakpoint never fired for us).
                if (cache.activeRecalculationId !== recalculationId) {
                    return
                }

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
         * re-check for the latest recalculation only when we have nothin loaded when the tab get's visible.
         * We want to preserver failure states, and re-fetching the latest complete recalculation would destroy
         * that state.
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
