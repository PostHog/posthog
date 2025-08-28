import { useActions, useValues } from 'kea'

import { IconInfo, IconList } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { IconAreaChart } from 'lib/lemon-ui/icons'

import { ExperimentMetric } from '~/queries/schema/schema-general'

import { experimentLogic } from '../../experimentLogic'
import { modalsLogic } from '../../modalsLogic'
import { MetricsReorderModal } from '../MetricsReorderModal'
import { AddPrimaryMetric, AddSecondaryMetric } from '../shared/AddMetric'
import { MetricsTable } from './MetricsTable'
import { ResultDetails } from './ResultDetails'

export function Metrics({ isSecondary }: { isSecondary?: boolean }): JSX.Element {
    const {
        experiment,
        getInsightType,
        getOrderedMetrics,
        primaryMetricsResults,
        secondaryMetricsResults,
        secondaryMetricsResultsErrors,
        primaryMetricsResultsErrors,
        hasMinimumExposureForResults,
    } = useValues(experimentLogic)

    const { openPrimaryMetricsReorderModal, openSecondaryMetricsReorderModal } = useActions(modalsLogic)

    const variants = experiment?.feature_flag?.filters?.multivariate?.variants
    if (!variants) {
        return <></>
    }

    const results = isSecondary ? secondaryMetricsResults : primaryMetricsResults
    const errors = isSecondary ? secondaryMetricsResultsErrors : primaryMetricsResultsErrors

    const metrics = getOrderedMetrics(!!isSecondary)

    const showResultDetails = metrics.length === 1 && results[0] && hasMinimumExposureForResults && !isSecondary

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
