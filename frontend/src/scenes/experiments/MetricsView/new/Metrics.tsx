import { useActions, useValues } from 'kea'

import { IconInfo, IconList } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconAreaChart } from 'lib/lemon-ui/icons'

import type { ExperimentMetric } from '~/queries/schema/schema-general'

import { experimentLogic } from '../../experimentLogic'
import { modalsLogic } from '../../modalsLogic'
import { MetricsReorderModal } from '../MetricsReorderModal'
import { AddPrimaryMetric, AddSecondaryMetric } from '../shared/AddMetric'
import { HowToReadTooltip } from './HowToReadTooltip'
import { MetricsTable } from './MetricsTable'
import { ResultDetails } from './ResultDetails'

export function Metrics({ isSecondary }: { isSecondary?: boolean }): JSX.Element | null {
    const {
        experiment,
        getInsightType,
        getOrderedMetrics,
        primaryMetricsResults,
        secondaryMetricsResults,
        secondaryMetricsResultsErrors,
        primaryMetricsResultsErrors,
        hasMinimumExposureForResults,
        featureFlags,
    } = useValues(experimentLogic)

    const { openPrimaryMetricsReorderModal, openSecondaryMetricsReorderModal } = useActions(modalsLogic)

    const variants = experiment?.feature_flag?.filters?.multivariate?.variants
    if (!variants) {
        return null
    }

    const unorderedResults = isSecondary ? secondaryMetricsResults : primaryMetricsResults
    const unorderedErrors = isSecondary ? secondaryMetricsResultsErrors : primaryMetricsResultsErrors

    const metrics = getOrderedMetrics(!!isSecondary)

    // Create maps of UUID -> result/error from original arrays
    const resultsMap = new Map()
    const errorsMap = new Map()

    // Get original metrics in their original order
    const originalMetrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const sharedMetrics = (experiment.saved_metrics || [])
        .filter((sharedMetric) => sharedMetric.metadata.type === (isSecondary ? 'secondary' : 'primary'))
        .map((sharedMetric) => sharedMetric.query)
    const allOriginalMetrics = [...originalMetrics, ...sharedMetrics]

    // Map results and errors by UUID
    allOriginalMetrics.forEach((metric, index) => {
        const uuid = metric.uuid || metric.query?.uuid
        if (uuid) {
            resultsMap.set(uuid, unorderedResults[index])
            errorsMap.set(uuid, unorderedErrors[index])
        }
    })

    // Reorder results and errors to match the ordered metrics
    const results = metrics.map((metric) => resultsMap.get(metric.uuid))
    const errors = metrics.map((metric) => errorsMap.get(metric.uuid))

    const showResultDetails = metrics.length === 1 && results[0] && hasMinimumExposureForResults && !isSecondary
    const hasSomeResults =
        results?.some((result) => result?.variant_results && result.variant_results.length > 0) &&
        hasMinimumExposureForResults
    const hasHowToReadTooltip = featureFlags[FEATURE_FLAGS.HOW_TO_READ_METRICS_EXPLANATION] === 'test'

    return (
        <div className="mb-4 -mt-2">
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
                        {hasSomeResults && !isSecondary && hasHowToReadTooltip && <HowToReadTooltip />}
                    </div>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto">
                        {metrics.length > 0 && (
                            <div className="mb-2 mt-4 justify-end flex gap-2">
                                {isSecondary ? <AddSecondaryMetric /> : <AddPrimaryMetric />}
                                {metrics.length > 1 && (
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        onClick={() =>
                                            isSecondary
                                                ? openSecondaryMetricsReorderModal()
                                                : openPrimaryMetricsReorderModal()
                                        }
                                        icon={<IconList />}
                                        tooltip="Reorder metrics"
                                    />
                                )}
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
                        isSecondary={!!isSecondary}
                        getInsightType={getInsightType}
                        showDetailsModal={!showResultDetails}
                    />
                    {showResultDetails && (
                        <div className="mt-4">
                            <ResultDetails
                                metric={metrics[0] as ExperimentMetric}
                                result={{
                                    ...results[0],
                                    metric: metrics[0] as ExperimentMetric,
                                }}
                                experiment={experiment}
                                isSecondary={!!isSecondary}
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
                        {isSecondary ? <AddSecondaryMetric /> : <AddPrimaryMetric />}
                    </div>
                </div>
            )}
        </div>
    )
}
