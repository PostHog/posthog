import { useActions, useValues } from 'kea'

import { IconInfo, IconList } from '@posthog/icons'
import { LemonButton, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { experimentMetricsLogic } from '~/scenes/experiments/experimentMetricsLogic'
import { AddMetricButton } from '~/scenes/experiments/Metrics/AddMetricButton'
import { METRIC_CONTEXTS } from '~/scenes/experiments/Metrics/experimentMetricModalLogic'
import { MetricsReorderModal } from '~/scenes/experiments/MetricsView/MetricsReorderModal'
import { modalsLogic } from '~/scenes/experiments/modalsLogic'
import {
    getExperimentVariants,
    isSavedExperiment,
    metricResults,
    type MetricWithResult,
} from '~/scenes/experiments/utils'
import { Experiment } from '~/types'

import { calculateAxisRange } from '../shared/utils'
import { HowToReadTooltip } from './HowToReadTooltip'
import { MetricsTable } from './MetricsTable'
import { ResultDetails } from './ResultDetails'

export function Metrics({ isSecondary }: { isSecondary?: boolean }): JSX.Element | null {
    const { experiment } = useValues(experimentLogic)

    const variants = getExperimentVariants(experiment)
    // Guard here so the child can take a non-null, real experiment and mount keyed child logics safely.
    if (!variants.length || !isSavedExperiment(experiment)) {
        return null
    }

    return <MetricsContent experiment={experiment} isSecondary={isSecondary} />
}

function MetricsContent({ experiment, isSecondary }: { experiment: Experiment; isSecondary?: boolean }): JSX.Element {
    const {
        getInsightType,
        orderedPrimaryMetricsWithResults,
        orderedSecondaryMetricsWithResults,
        hasMinimumExposureForResults,
        metricAxesSynced,
    } = useValues(experimentLogic)
    const { setMetricAxesSynced } = useActions(experimentLogic)
    const {
        primaryMetricsResults,
        primaryMetricsResultsErrors,
        secondaryMetricsResults,
        secondaryMetricsResultsErrors,
    } = useValues(experimentMetricsLogic({ experiment }))
    const { featureFlags } = useValues(featureFlagLogic)
    const recalculationFlow = !!featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]

    const { openPrimaryMetricsReorderModal, openSecondaryMetricsReorderModal } = useActions(modalsLogic)

    const resolveMetricsWithResults = (secondary: boolean): MetricWithResult[] =>
        recalculationFlow
            ? metricResults(experiment)(
                  secondary ? secondaryMetricsResults : primaryMetricsResults,
                  secondary ? secondaryMetricsResultsErrors : primaryMetricsResultsErrors,
                  secondary ? 'secondary' : 'primary'
              )
            : secondary
              ? orderedSecondaryMetricsWithResults
              : orderedPrimaryMetricsWithResults

    const metricsWithResults = resolveMetricsWithResults(!!isSecondary)
    const otherSectionMetricsWithResults = resolveMetricsWithResults(!isSecondary)

    const metrics = metricsWithResults.map(({ metric }) => metric)
    const results = metricsWithResults.map(({ result }) => result)
    const errors = metricsWithResults.map(({ error }) => error)
    const metricIndexes = metricsWithResults.map(({ metricIndex }) => metricIndex)

    const otherSectionResults = otherSectionMetricsWithResults.map(({ result }) => result)
    const axisRange = calculateAxisRange(metricAxesSynced ? [...results, ...otherSectionResults] : results)
    // Syncing only changes anything once both sections have chartable results
    const sectionHasChartableResult = (sectionResults: MetricWithResult['result'][]): boolean =>
        sectionResults.some((result) => !!result?.variant_results?.length)
    const showAxisSyncToggle = sectionHasChartableResult(results) && sectionHasChartableResult(otherSectionResults)

    const showResultDetails = metrics.length === 1 && results[0] && hasMinimumExposureForResults && !isSecondary
    const hasSomeResults =
        results?.some((result) => result?.variant_results && result.variant_results.length > 0) &&
        hasMinimumExposureForResults

    return (
        <div className="mb-4 -mt-2" data-attr="experiment-creation-goal-metric">
            {experiment?.id && (
                <>
                    <MetricsReorderModal isSecondary={false} />
                    <MetricsReorderModal isSecondary={true} />
                </>
            )}
            <div className="flex">
                <div className="w-1/2 pt-5">
                    <div className="inline-flex items-center deprecated-space-x-2 mb-0">
                        <h2 className="mb-0 font-semibold text-lg leading-6">
                            {isSecondary ? 'Secondary metrics' : 'Primary metrics'}
                        </h2>
                        {metrics.length > 0 && (
                            <Tooltip
                                title={
                                    isSecondary
                                        ? 'Secondary metrics capture additional outcomes or behaviors affected by your experiment. They help you understand broader impacts and potential side effects beyond the primary goal.'
                                        : 'Primary metrics represent the main goal of your experiment. They directly measure whether your hypothesis was successful and are the key factor in deciding if the test achieved its primary objective.'
                                }
                            >
                                <IconInfo className="text-secondary text-lg" />
                            </Tooltip>
                        )}
                        {hasSomeResults && !isSecondary && <HowToReadTooltip />}
                    </div>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto">
                        {metrics.length > 0 && (
                            <div className="mb-2 mt-4 justify-end flex items-center gap-2">
                                {showAxisSyncToggle && (
                                    <LemonSwitch
                                        checked={metricAxesSynced}
                                        onChange={setMetricAxesSynced}
                                        size="xsmall"
                                        bordered
                                        label="Sync axes"
                                        tooltip="Use the same scale for primary and secondary metric charts. Turn off to scale each section to its own results."
                                        data-attr="experiment-sync-metric-axes"
                                    />
                                )}
                                <AddMetricButton
                                    metricContext={isSecondary ? METRIC_CONTEXTS.secondary : METRIC_CONTEXTS.primary}
                                />
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    onClick={() =>
                                        isSecondary
                                            ? openSecondaryMetricsReorderModal()
                                            : openPrimaryMetricsReorderModal()
                                    }
                                    icon={<IconList />}
                                    tooltip="Reorder, move or remove metrics"
                                />
                            </div>
                        )}
                    </div>
                </div>
            </div>
            {metrics.length > 0 ? (
                <>
                    <MetricsTable
                        metrics={metrics}
                        results={results}
                        errors={errors}
                        metricIndexes={metricIndexes}
                        isSecondary={!!isSecondary}
                        axisRange={axisRange}
                        getInsightType={getInsightType}
                        showDetailsModal={!showResultDetails}
                    />
                    {showResultDetails && results[0] && (
                        <div className="mt-4">
                            <ResultDetails
                                metric={metrics[0] as ExperimentMetric}
                                result={results[0]}
                                experiment={experiment}
                            />
                        </div>
                    )}
                </>
            ) : (
                <div className="border rounded bg-surface-primary pt-6 pb-8 text-secondary mt-2">
                    <div className="flex flex-col items-center mx-auto deprecated-space-y-3">
                        <IconAreaChart fontSize="30" />
                        <div className="text-sm text-center text-balance max-w-sm">
                            <p>
                                {isSecondary
                                    ? 'Secondary metrics provide additional context and help detect unintended side effects.'
                                    : 'Primary metrics represent the main goal of the experiment and directly measure if your hypothesis was successful.'}
                            </p>
                        </div>
                        <AddMetricButton
                            metricContext={isSecondary ? METRIC_CONTEXTS.secondary : METRIC_CONTEXTS.primary}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}
