import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { Experiment } from '~/types'

import { experimentLogic, previousRefreshAnalytics } from '../experimentLogic'
import { experimentMetricsLogic } from '../experimentMetricsLogic'
import { ExperimentReloadAction } from './ExperimentReloadAction'

/**
 * Wires the reload button to the right loading source: on the recalculation flow it reads
 * experimentMetricsLogic (progress + isRecalculating, triggers a fresh recalculation on click);
 * otherwise it mirrors the legacy primary/secondary loading rules from experimentLogic.
 *
 * Rendered only for non-draft experiments, so `experiment` is always real here.
 */
export function ExperimentReloadActionContainer({
    experiment,
    lastRefresh,
}: {
    experiment: Experiment
    /** Legacy "last refreshed" timestamp from experimentLogic results, used only on the legacy path.
     * The recalculation path derives its own from the completed run. */
    lastRefresh: string
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const recalculationFlow = !!featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]

    return recalculationFlow ? (
        <RecalculationReloadAction experiment={experiment} />
    ) : (
        <LegacyReloadAction experiment={experiment} lastRefresh={lastRefresh} />
    )
}

function RecalculationReloadAction({ experiment }: { experiment: Experiment }): JSX.Element {
    const metricsLogic = experimentMetricsLogic({ experiment })
    const { isRecalculating, recalculationProgress, lastRefresh } = useValues(metricsLogic)
    const { triggerRecalculation } = useActions(metricsLogic)
    const { autoRefresh, currentRefresh } = useValues(experimentLogic)
    const { refreshExperimentResults, reportExperimentMetricsRefreshed } = useActions(experimentLogic)

    return (
        <ExperimentReloadAction
            isRefreshing={isRecalculating}
            lastRefresh={lastRefresh}
            progress={recalculationProgress}
            onClick={() => {
                reportExperimentMetricsRefreshed(experiment, true, {
                    triggered_by: 'manual',
                    auto_refresh_enabled: autoRefresh.enabled,
                    auto_refresh_interval: autoRefresh.interval,
                    ...previousRefreshAnalytics(currentRefresh),
                })
                triggerRecalculation()
                // Exposures still live in experimentLogic; keep refreshing them on manual reload.
                refreshExperimentResults(true, 'manual')
            }}
        />
    )
}

function LegacyReloadAction({ experiment, lastRefresh }: { experiment: Experiment; lastRefresh: string }): JSX.Element {
    const { primaryMetricsResultsLoading, secondaryMetricsResultsLoading, autoRefresh, currentRefresh } =
        useValues(experimentLogic)
    const { refreshExperimentResults, reportExperimentMetricsRefreshed } = useActions(experimentLogic)

    return (
        <ExperimentReloadAction
            isRefreshing={primaryMetricsResultsLoading || secondaryMetricsResultsLoading}
            lastRefresh={lastRefresh}
            onClick={() => {
                reportExperimentMetricsRefreshed(experiment, true, {
                    triggered_by: 'manual',
                    auto_refresh_enabled: autoRefresh.enabled,
                    auto_refresh_interval: autoRefresh.interval,
                    ...previousRefreshAnalytics(currentRefresh),
                })
                refreshExperimentResults(true, 'manual')
            }}
        />
    )
}
