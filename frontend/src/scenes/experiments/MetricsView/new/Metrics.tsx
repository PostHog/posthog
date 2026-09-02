import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { SummarizeExperimentButton } from '~/scenes/experiments/components/SummarizeExperimentButton'
import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { experimentMetricsLogic } from '~/scenes/experiments/experimentMetricsLogic'
import { AddMetricButton } from '~/scenes/experiments/Metrics/AddMetricButton'
import { METRIC_CONTEXTS } from '~/scenes/experiments/Metrics/experimentMetricModalLogic'
import { getExperimentVariants, isSavedExperiment, metricResults } from '~/scenes/experiments/utils'
import { Experiment } from '~/types'

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
    } = useValues(experimentLogic)
    const {
        primaryMetricsResults,
        primaryMetricsResultsErrors,
        secondaryMetricsResults,
        secondaryMetricsResultsErrors,
    } = useValues(experimentMetricsLogic({ experiment }))
    const { featureFlags } = useValues(featureFlagLogic)
    const recalculationFlow = !!featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]

    const type = isSecondary ? 'secondary' : 'primary'

    const metricsWithResults = recalculationFlow
        ? metricResults(experiment)(
              isSecondary ? secondaryMetricsResults : primaryMetricsResults,
              isSecondary ? secondaryMetricsResultsErrors : primaryMetricsResultsErrors,
              type
          )
        : isSecondary
          ? orderedSecondaryMetricsWithResults
          : orderedPrimaryMetricsWithResults

    const metrics = metricsWithResults.map(({ metric }) => metric)
    const results = metricsWithResults.map(({ result }) => result)
    const errors = metricsWithResults.map(({ error }) => error)
    const metricIndexes = metricsWithResults.map(({ metricIndex }) => metricIndex)

    const showResultDetails = metrics.length === 1 && results[0] && hasMinimumExposureForResults && !isSecondary
    const hasSomeResults =
        results?.some((result) => result?.variant_results && result.variant_results.length > 0) &&
        hasMinimumExposureForResults

    return (
        <div className="mb-4 -mt-2" data-attr="experiment-creation-goal-metric">
            <div className="flex">
                <div className="w-1/2 pt-5">
                    <div className="inline-flex items-center deprecated-space-x-2 mb-0">
                        <h2 className="mb-0 font-semibold text-lg leading-6">
                            {isSecondary ? 'Secondary metrics' : 'Primary metrics'}
                        </h2>
                        {isSecondary && metrics.length > 0 && (
                            <Tooltip title="Secondary metrics capture additional outcomes or behaviors affected by your experiment. They help you understand broader impacts and potential side effects beyond the primary goal.">
                                <IconInfo className="text-secondary text-lg" />
                            </Tooltip>
                        )}
                        {!isSecondary && hasMinimumExposureForResults && <SummarizeExperimentButton />}
                        {hasSomeResults && !isSecondary && <HowToReadTooltip />}
                    </div>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto">
                        {metrics.length > 0 && (
                            <div className="mb-2 mt-4 justify-end flex items-center gap-2">
                                <AddMetricButton
                                    metricContext={isSecondary ? METRIC_CONTEXTS.secondary : METRIC_CONTEXTS.primary}
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
                        getInsightType={getInsightType}
                        showDetailsModal={!showResultDetails}
                    />
                    {showResultDetails && (
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
