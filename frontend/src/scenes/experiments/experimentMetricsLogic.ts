import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, type FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import type { Breakdown, CachedNewExperimentQueryResponse, ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { experimentsMetricsRecalculationLatestRetrieve } from 'products/experiments/frontend/generated/api'
import type { ExperimentMetricsRecalculationApi } from 'products/experiments/frontend/generated/api.schemas'

import type { experimentMetricsLogicType } from './experimentMetricsLogicType'

type ExperimentSavedMetric = {
    metadata: {
        type: 'primary' | 'secondary'
        breakdowns?: Breakdown[]
    }
    query: ExperimentMetric
}

export interface ExperimentMetricsLogicProps {
    /** This logic only exists for a real, saved experiment — `experiment` is always present and
     * carries the id, so there is no separate experimentId prop. */
    experiment: Experiment
}

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

const buildRecalculationResultsByPosition = (
    experiment: Experiment,
    polledResults: readonly { metric_uuid: string; result: unknown }[] | undefined,
    type: 'primary' | 'secondary'
): CachedNewExperimentQueryResponse[] => {
    if (!polledResults) {
        return []
    }
    const sharedMetrics = sharedMetricsToExperimentMetrics(experiment.saved_metrics as ExperimentSavedMetric[], type)
    const inline = (type === 'primary' ? experiment.metrics : experiment.metrics_secondary) || []
    const metrics: ExperimentMetric[] = [...(inline as ExperimentMetric[]), ...sharedMetrics]
    const resultByUuid = new Map(polledResults.map((r) => [r.metric_uuid, r.result]))
    return metrics.map((metric) => resultByUuid.get(metric.uuid as string) as CachedNewExperimentQueryResponse)
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
        setPrimaryMetricsResults: (results: CachedNewExperimentQueryResponse[]) => ({ results }),
        setSecondaryMetricsResults: (results: CachedNewExperimentQueryResponse[]) => ({ results }),
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
    }),
    selectors({
        // The recalculation flow does not surface per-metric errors as positional arrays yet — errors
        // live on currentRecalculation.metric_errors. Expose empty arrays so consumers have the same
        // shape as the legacy path; populate these in a later step.
        primaryMetricsResultsErrors: [() => [], (): unknown[] => []],
        secondaryMetricsResultsErrors: [() => [], (): unknown[] => []],
    }),
    listeners(({ actions, values, props }) => ({
        loadLatestRecalculation: async () => {
            /**
             * bail if the feature flag is not enabled
             */
            if (!(values.featureFlags as FeatureFlagsSet)[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]) {
                return
            }
            const projectId = values.currentProjectId
            const experimentId = props.experiment.id
            if (!projectId || typeof experimentId !== 'number') {
                return
            }
            try {
                const recalc = await experimentsMetricsRecalculationLatestRetrieve(String(projectId), experimentId)
                actions.setCurrentRecalculation(recalc)
                actions.setPrimaryMetricsResults(
                    buildRecalculationResultsByPosition(props.experiment, recalc.results, 'primary')
                )
                actions.setSecondaryMetricsResults(
                    buildRecalculationResultsByPosition(props.experiment, recalc.results, 'secondary')
                )
            } catch (error: any) {
                if (error?.status === 404) {
                    // No completed recalculation yet — leave existing state alone.
                    return
                }
                lemonToast.error('Failed to load latest recalculation')
            } finally {
                actions.setRecalculationLoading(false)
            }
        },
    })),
    afterMount(({ actions }) => {
        // Fetch the latest completed recalculation on mount; the listener no-ops when the flag is off.
        actions.loadLatestRecalculation()
    }),
])
