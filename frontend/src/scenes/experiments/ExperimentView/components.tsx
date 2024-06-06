import '../Experiment.scss'

import { IconArchive, IconCheck, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { PageHeader } from 'lib/components/PageHeader'
import { dayjs } from 'lib/dayjs'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { ExperimentResults, FilterType, InsightShortId, InsightType } from '~/types'

import { ResetButton } from '../Experiment'
import { experimentLogic } from '../experimentLogic'
import { getExperimentInsightColour, transformResultFilters } from '../utils'

export function VariantTag({ variantKey }: { variantKey: string }): JSX.Element {
    const { experimentResults, getIndexForVariant } = useValues(experimentLogic)

    return (
        <span className="flex items-center space-x-1">
            <div
                className="w-2 h-2 rounded-full mr-0.5"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    backgroundColor: getExperimentInsightColour(getIndexForVariant(experimentResults, variantKey)),
                }}
            />
            <span className="font-semibold">{capitalizeFirstLetter(variantKey)}</span>
        </span>
    )
}

export function ResultsTag(): JSX.Element {
    const { areResultsSignificant, significanceDetails } = useValues(experimentLogic)
    const result: { color: LemonTagType; label: string } = areResultsSignificant
        ? { color: 'success', label: 'Significant' }
        : { color: 'primary', label: 'Not significant' }

    if (significanceDetails) {
        return (
            <Tooltip title={significanceDetails}>
                <LemonTag className="cursor-pointer" type={result.color}>
                    <b className="uppercase">{result.label}</b>
                </LemonTag>
            </Tooltip>
        )
    }

    return (
        <LemonTag type={result.color}>
            <b className="uppercase">{result.label}</b>
        </LemonTag>
    )
}

export function ResultsQuery({
    targetResults,
    showTable,
}: {
    targetResults: ExperimentResults['result'] | null
    showTable: boolean
}): JSX.Element {
    return (
        <Query
            query={{
                kind: NodeKind.InsightVizNode,
                source: filtersToQueryNode(transformResultFilters(targetResults?.filters ?? {})),
                showTable,
                showLastComputation: true,
                showLastComputationRefresh: false,
            }}
            context={{
                insightProps: {
                    dashboardItemId: targetResults?.fakeInsightId as InsightShortId,
                    cachedInsight: {
                        short_id: targetResults?.fakeInsightId as InsightShortId,
                        filters: transformResultFilters(targetResults?.filters ?? {}),
                        result: targetResults?.insight,
                        disable_baseline: true,
                        last_refresh: targetResults?.last_refresh,
                    },
                    doNotLoad: true,
                },
            }}
            readOnly
        />
    )
}

export function ExploreButton({ icon = <IconAreaChart /> }: { icon?: JSX.Element }): JSX.Element {
    const { experimentResults, experiment } = useValues(experimentLogic)

    // keep in sync with https://github.com/PostHog/posthog/blob/master/ee/clickhouse/queries/experiments/funnel_experiment_result.py#L71
    // :TRICKY: In the case of no results, we still want users to explore the query, so they can debug further.
    // This generates a close enough query that the backend would use to compute results.
    const filtersFromExperiment: Partial<FilterType> = {
        ...experiment.filters,
        date_from: experiment.start_date,
        date_to: experiment.end_date,
        explicit_date: true,
        breakdown: `$feature/${experiment.feature_flag_key ?? experiment.feature_flag?.key}`,
        breakdown_type: 'event',
        properties: [],
    }

    return (
        <LemonButton
            className="ml-auto -translate-y-2"
            size="small"
            type="primary"
            icon={icon}
            to={urls.insightNew(
                undefined,
                undefined,
                JSON.stringify({
                    kind: NodeKind.InsightVizNode,
                    source: filtersToQueryNode(
                        transformResultFilters(
                            experimentResults?.filters
                                ? { ...experimentResults.filters, explicit_date: true }
                                : filtersFromExperiment
                        )
                    ),
                    showTable: true,
                    showLastComputation: true,
                    showLastComputationRefresh: false,
                })
            )}
        >
            Explore results
        </LemonButton>
    )
}

export function ResultsHeader(): JSX.Element {
    return (
        <div className="flex">
            <div className="w-1/2">
                <div className="inline-flex items-center space-x-2 mb-2">
                    <h2 className="m-0 font-semibold text-lg">Results</h2>
                    <ResultsTag />
                </div>
            </div>

            <div className="w-1/2 flex flex-col justify-end">
                <div className="ml-auto">
                    <ExploreButton />
                </div>
            </div>
        </div>
    )
}

export function NoResultsEmptyState(): JSX.Element {
    const { experimentResultsLoading, experimentResultCalculationError } = useValues(experimentLogic)

    function ChecklistItem({ failureReason, checked }: { failureReason: string; checked: boolean }): JSX.Element {
        const failureReasonToText = {
            'no-events': 'Events have been received',
            'no-flag-info': 'Feature flag information is present on the events',
            'no-control-variant': 'Events with the control variant received',
            'no-test-variant': 'Events with at least one test variant received',
        }

        return (
            <div className="flex items-center space-x-2">
                {checked ? (
                    <IconCheck className="text-success" fontSize={16} />
                ) : (
                    <IconX className="text-danger" fontSize={16} />
                )}
                <span className={checked ? 'text-muted' : ''}>{failureReasonToText[failureReason]}</span>
            </div>
        )
    }

    if (experimentResultsLoading) {
        return <></>
    }

    // Validation errors return 400 and are rendered as a checklist
    if (experimentResultCalculationError?.statusCode === 400) {
        const checklistItems = []
        for (const [failureReason, value] of Object.entries(JSON.parse(experimentResultCalculationError.detail))) {
            checklistItems.push(<ChecklistItem key={failureReason} failureReason={failureReason} checked={!value} />)
        }

        return (
            <div>
                <div className="border rounded bg-bg-light py-2">
                    <div className="flex space-x-2">
                        <div className="w-1/2 my-auto px-6 space-y-4 items-center">
                            <div className="flex items-center">
                                <div className="font-semibold leading-tight text-base text-current">
                                    Experiment results are not yet available
                                </div>
                            </div>
                            <div className="text-muted">
                                Results will be calculated once we've received the necessary events. The checklist on
                                the right shows what's still needed.
                            </div>
                        </div>
                        <LemonDivider vertical />
                        <div className="w-1/2 flex py-4 px-6 items-center">
                            <div className="space-y-2">{checklistItems}</div>
                        </div>
                    </div>
                </div>
            </div>
        )
    }

    // Non-400 errors are rendered as plain text
    return (
        <div>
            <div className="border rounded bg-bg-light py-10">
                <div className="flex flex-col items-center mx-auto text-muted space-y-2">
                    <IconArchive className="text-4xl text-secondary-3000" />
                    <h2 className="text-xl font-semibold leading-tight">There are no experiment results yet</h2>
                    {!!experimentResultCalculationError && (
                        <div className="text-sm text-center text-balance">
                            {experimentResultCalculationError.detail}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

export function EllipsisAnimation(): JSX.Element {
    const [ellipsis, setEllipsis] = useState('.')

    useEffect(() => {
        let count = 1
        let direction = 1

        const interval = setInterval(() => {
            setEllipsis('.'.repeat(count))
            count += direction

            if (count === 3 || count === 1) {
                direction *= -1
            }
        }, 300)

        return () => clearInterval(interval)
    }, [])

    return <span>{ellipsis}</span>
}

export function ExperimentLoadingAnimation(): JSX.Element {
    return (
        <div className="flex flex-col flex-1 justify-center items-center">
            <Animation type={AnimationType.LaptopHog} />
            <div className="text-xs text-muted w-44">
                <span className="mr-1">Fetching experiment results</span>
                <EllipsisAnimation />
            </div>
        </div>
    )
}

export function PageHeaderCustom(): JSX.Element {
    const { experiment, isExperimentRunning, isExperimentStopped } = useValues(experimentLogic)
    const {
        launchExperiment,
        resetRunningExperiment,
        endExperiment,
        archiveExperiment,
        setEditExperiment,
        loadExperimentResults,
        loadSecondaryMetricResults,
        createExposureCohort,
    } = useActions(experimentLogic)

    const exposureCohortId = experiment?.exposure_cohort

    return (
        <PageHeader
            buttons={
                <>
                    {experiment && !isExperimentRunning && (
                        <div className="flex items-center">
                            <LemonButton type="secondary" className="mr-2" onClick={() => setEditExperiment(true)}>
                                Edit
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                data-attr="launch-experiment"
                                onClick={() => launchExperiment()}
                            >
                                Launch
                            </LemonButton>
                        </div>
                    )}
                    {experiment && isExperimentRunning && (
                        <div className="flex flex-row gap-2">
                            {!isExperimentStopped && !experiment.archived && (
                                <>
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton
                                                    onClick={() =>
                                                        exposureCohortId ? undefined : createExposureCohort()
                                                    }
                                                    fullWidth
                                                    data-attr={`${
                                                        exposureCohortId ? 'view' : 'create'
                                                    }-exposure-cohort`}
                                                    to={exposureCohortId ? urls.cohort(exposureCohortId) : undefined}
                                                    targetBlank={!!exposureCohortId}
                                                >
                                                    {exposureCohortId ? 'View' : 'Create'} exposure cohort
                                                </LemonButton>
                                                <LemonButton
                                                    onClick={() => loadExperimentResults(true)}
                                                    fullWidth
                                                    data-attr="refresh-experiment"
                                                >
                                                    Refresh experiment results
                                                </LemonButton>
                                                <LemonButton
                                                    onClick={() => loadSecondaryMetricResults(true)}
                                                    fullWidth
                                                    data-attr="refresh-secondary-metrics"
                                                >
                                                    Refresh secondary metrics
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                    <LemonDivider vertical />
                                </>
                            )}
                            <ResetButton experiment={experiment} onConfirm={resetRunningExperiment} />
                            {!experiment.end_date && (
                                <LemonButton
                                    type="secondary"
                                    data-attr="stop-experiment"
                                    status="danger"
                                    onClick={() => endExperiment()}
                                >
                                    Stop
                                </LemonButton>
                            )}
                            {isExperimentStopped && (
                                <LemonButton type="secondary" status="danger" onClick={() => archiveExperiment()}>
                                    <b>Archive</b>
                                </LemonButton>
                            )}
                        </div>
                    )}
                </>
            }
        />
    )
}

export function ActionBanner(): JSX.Element {
    const {
        experiment,
        experimentInsightType,
        experimentResults,
        experimentLoading,
        experimentResultsLoading,
        isExperimentRunning,
        areResultsSignificant,
        isExperimentStopped,
        funnelResultsPersonsTotal,
        actualRunningTime,
        getHighestProbabilityVariant,
    } = useValues(experimentLogic)

    const { archiveExperiment } = useActions(experimentLogic)

    const recommendedRunningTime = experiment?.parameters?.recommended_running_time || 1
    const recommendedSampleSize = experiment?.parameters?.recommended_sample_size || 100

    if (!experiment || experimentLoading || experimentResultsLoading) {
        return <></>
    }

    // Draft
    if (!isExperimentRunning) {
        return (
            <LemonBanner type="info" className="mt-4">
                Your experiment is in draft mode. You can edit your variants, adjust release conditions, and{' '}
                <Link className="font-semibold" to="https://posthog.com/docs/experiments/testing-and-launching">
                    test your feature flag
                </Link>
                . Once everything works as expected, you can launch your experiment. From that point, any new experiment
                events will be counted towards the results.
            </LemonBanner>
        )
    }

    // Running, results present, not significant
    if (isExperimentRunning && experimentResults && !isExperimentStopped && !areResultsSignificant) {
        // Results insignificant, but a large enough sample/running time has been achieved
        // Further collection unlikely to change the result -> recommmend cutting the losses
        if (
            experimentInsightType === InsightType.FUNNELS &&
            funnelResultsPersonsTotal > Math.max(recommendedSampleSize, 500) &&
            dayjs().diff(experiment.start_date, 'day') > 2 // at least 2 days running
        ) {
            return (
                <LemonBanner type="warning" className="mt-4">
                    You've reached a sufficient sample size for your experiment, but the results are still inconclusive.
                    Continuing the experiment is unlikely to yield significant findings. It may be time to stop this
                    experiment.
                </LemonBanner>
            )
        }
        if (experimentInsightType === InsightType.TRENDS && actualRunningTime > Math.max(recommendedRunningTime, 7)) {
            return (
                <LemonBanner type="warning" className="mt-4">
                    Your experiment has been running long enough, but the results are still inconclusive. Continuing the
                    experiment is unlikely to yield significant findings. It may be time to stop this experiment.
                </LemonBanner>
            )
        }

        return (
            <LemonBanner type="info" className="mt-4">
                Your experiment is live and collecting data, but hasn't yet reached the statistical significance needed
                to make reliable decisions. It's important to wait for more data to avoid premature conclusions.
            </LemonBanner>
        )
    }

    // Running, results significant
    if (isExperimentRunning && !isExperimentStopped && areResultsSignificant && experimentResults) {
        const { probability } = experimentResults
        const winningVariant = getHighestProbabilityVariant(experimentResults)
        if (!winningVariant) {
            return <></>
        }

        const winProbability = probability[winningVariant]

        // Win probability only slightly over 0.9 and the recommended sample/time just met -> proceed with caution
        if (
            experimentInsightType === InsightType.FUNNELS &&
            funnelResultsPersonsTotal < recommendedSampleSize + 50 &&
            winProbability < 0.93
        ) {
            return (
                <LemonBanner type="info" className="mt-4">
                    You've achieved significant results, however, the sample size barely meets the minimum requirements,
                    and the win probability is marginally above 90%. To ensure more reliable outcomes, consider running
                    the experiment longer.
                </LemonBanner>
            )
        }

        if (
            experimentInsightType === InsightType.TRENDS &&
            actualRunningTime < recommendedRunningTime + 2 &&
            winProbability < 0.93
        ) {
            return (
                <LemonBanner type="info" className="mt-4">
                    You've achieved significant results, however, the running time barely meets the minimum
                    requirements, and the win probability is marginally above 90%. To ensure more reliable outcomes,
                    consider running the experiment longer.
                </LemonBanner>
            )
        }

        return (
            <LemonBanner type="success" className="mt-4">
                Good news! Your experiment has gathered enough data to reach statistical significance, providing
                reliable results for decision making. Before taking any action, review relevant secondary metrics for
                any unintended side effects. Once you're done, you can stop the experiment.
            </LemonBanner>
        )
    }

    // Stopped, results significant
    if (isExperimentStopped && areResultsSignificant) {
        return (
            <LemonBanner type="success" className="mt-4">
                You have stopped this experiment, and it is no longer collecting data. With significant results in hand,
                you can now roll out the winning variant to all your users by adjusting the{' '}
                <Link
                    target="_blank"
                    className="font-semibold"
                    to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                >
                    {experiment.feature_flag?.key}
                </Link>{' '}
                feature flag.
            </LemonBanner>
        )
    }

    // Stopped, results not significant
    if (isExperimentStopped && experimentResults && !areResultsSignificant) {
        return (
            <LemonBanner type="info" className="mt-4">
                You have stopped this experiment, and it is no longer collecting data. Because your results are not
                significant, we don't recommend drawing any conclusions from them. You can reset the experiment
                (deleting the data collected so far) and restart the experiment at any point again. If this experiment
                is no longer relevant, you can{' '}
                <Link className="font-semibold" onClick={() => archiveExperiment()}>
                    archive it
                </Link>
                .
            </LemonBanner>
        )
    }

    return <></>
}
