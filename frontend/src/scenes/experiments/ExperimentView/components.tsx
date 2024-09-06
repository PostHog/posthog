import '../Experiment.scss'

import { IconArchive, IconCheck, IconFlask, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonTag,
    LemonTagType,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryFromFilters } from '~/queries/nodes/InsightViz/utils'
import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind } from '~/queries/schema'
import {
    Experiment,
    Experiment as ExperimentType,
    ExperimentResults,
    FilterType,
    InsightShortId,
    InsightType,
} from '~/types'

import { experimentLogic } from '../experimentLogic'
import { getExperimentStatus, getExperimentStatusColor } from '../experimentsLogic'
import { getExperimentInsightColour, transformResultFilters } from '../utils'

export function VariantTag({
    experimentId,
    variantKey,
}: {
    experimentId: number | 'new'
    variantKey: string
}): JSX.Element {
    const { experimentResults, getIndexForVariant } = useValues(experimentLogic({ experimentId }))

    return (
        <span className="flex items-center space-x-1">
            <div
                className="w-2 h-2 rounded-full mr-0.5"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    backgroundColor: getExperimentInsightColour(getIndexForVariant(experimentResults, variantKey)),
                }}
            />
            <span className="font-semibold">{variantKey}</span>
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
                        query: targetResults?.filters
                            ? queryFromFilters(transformResultFilters(targetResults.filters))
                            : null,
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

    const query: InsightVizNode = {
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
    }

    return (
        <LemonButton
            className="ml-auto -translate-y-2"
            size="xsmall"
            type="primary"
            icon={icon}
            to={urls.insightNew(undefined, undefined, query)}
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
    type ErrorCode = 'no-events' | 'no-flag-info' | 'no-control-variant' | 'no-test-variant'

    const { experimentResultsLoading, experimentResultCalculationError } = useValues(experimentLogic)

    function ChecklistItem({ errorCode, value }: { errorCode: ErrorCode; value: boolean }): JSX.Element {
        const failureText = {
            'no-events': 'Experiment events not received',
            'no-flag-info': 'Feature flag information not present on the events',
            'no-control-variant': 'Events with the control variant not received',
            'no-test-variant': 'Events with at least one test variant not received',
        }

        const successText = {
            'no-events': 'Experiment events have been received',
            'no-flag-info': 'Feature flag information is present on the events',
            'no-control-variant': 'Events with the control variant received',
            'no-test-variant': 'Events with at least one test variant received',
        }

        return (
            <div className="flex items-center space-x-2">
                {value === false ? (
                    <>
                        <IconCheck className="text-success" fontSize={16} />
                        <span className="text-muted">{successText[errorCode]}</span>
                    </>
                ) : (
                    <>
                        <IconX className="text-danger" fontSize={16} />
                        <span>{failureText[errorCode]}</span>
                    </>
                )}
            </div>
        )
    }

    if (experimentResultsLoading) {
        return <></>
    }

    // Validation errors return 400 and are rendered as a checklist
    if (experimentResultCalculationError?.statusCode === 400) {
        let parsedDetail: Record<ErrorCode, boolean>
        try {
            parsedDetail = JSON.parse(experimentResultCalculationError.detail)
        } catch (error) {
            return (
                <div className="border rounded bg-bg-light p-4">
                    <div className="font-semibold leading-tight text-base text-current">
                        Experiment results could not be calculated
                    </div>
                    <div className="mt-2">{experimentResultCalculationError.detail}</div>
                </div>
            )
        }

        const checklistItems = []
        for (const [errorCode, value] of Object.entries(parsedDetail)) {
            checklistItems.push(<ChecklistItem key={errorCode} errorCode={errorCode as ErrorCode} value={value} />)
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

    if (experimentResultCalculationError?.statusCode === 504) {
        return (
            <div>
                <div className="border rounded bg-bg-light py-10">
                    <div className="flex flex-col items-center mx-auto text-muted space-y-2">
                        <IconArchive className="text-4xl text-secondary-3000" />
                        <h2 className="text-xl font-semibold leading-tight">Experiment results timed out</h2>
                        {!!experimentResultCalculationError && (
                            <div className="text-sm text-center text-balance">
                                This may occur when the experiment has a large amount of data or is particularly
                                complex. We are actively working on fixing this. In the meantime, please try refreshing
                                the experiment to retrieve the results.
                            </div>
                        )}
                    </div>
                </div>
            </div>
        )
    }

    // Other unexpected errors
    return (
        <div>
            <div className="border rounded bg-bg-light py-10">
                <div className="flex flex-col items-center mx-auto text-muted space-y-2">
                    <IconArchive className="text-4xl text-secondary-3000" />
                    <h2 className="text-xl font-semibold leading-tight">Experiment results could not be calculated</h2>
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
    const {
        experimentId,
        experiment,
        isExperimentRunning,
        isExperimentStopped,
        areResultsSignificant,
        isSingleVariantShipped,
        featureFlags,
    } = useValues(experimentLogic)
    const {
        launchExperiment,
        endExperiment,
        archiveExperiment,
        setEditExperiment,
        loadExperimentResults,
        loadSecondaryMetricResults,
        createExposureCohort,
        openShipVariantModal,
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
                            <ResetButton experimentId={experiment.id} />
                            {!experiment.end_date && (
                                <LemonButton
                                    type="secondary"
                                    data-attr="stop-experiment"
                                    status="danger"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Stop this experiment?',
                                            content: (
                                                <div className="text-sm text-muted">
                                                    This action will end data collection. The experiment can be
                                                    restarted later if needed.
                                                </div>
                                            ),
                                            primaryButton: {
                                                children: 'Stop',
                                                type: 'primary',
                                                onClick: () => endExperiment(),
                                                size: 'small',
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                                type: 'tertiary',
                                                size: 'small',
                                            },
                                        })
                                    }}
                                >
                                    Stop
                                </LemonButton>
                            )}
                            {isExperimentStopped && (
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Archive this experiment?',
                                            content: (
                                                <div className="text-sm text-muted">
                                                    This action will move the experiment to the archived tab. It can be
                                                    restored at any time.
                                                </div>
                                            ),
                                            primaryButton: {
                                                children: 'Archive',
                                                type: 'primary',
                                                onClick: () => archiveExperiment(),
                                                size: 'small',
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                                type: 'tertiary',
                                                size: 'small',
                                            },
                                        })
                                    }}
                                >
                                    <b>Archive</b>
                                </LemonButton>
                            )}
                        </div>
                    )}
                    {featureFlags[FEATURE_FLAGS.EXPERIMENT_MAKE_DECISION] &&
                        areResultsSignificant &&
                        !isSingleVariantShipped && (
                            <>
                                <Tooltip title="Choose a variant and roll it out to all users">
                                    <LemonButton
                                        type="primary"
                                        icon={<IconFlask />}
                                        onClick={() => openShipVariantModal()}
                                    >
                                        <b>Ship a variant</b>
                                    </LemonButton>
                                </Tooltip>
                                <ShipVariantModal experimentId={experimentId} />
                            </>
                        )}
                </>
            }
        />
    )
}

export function ShipVariantModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, sortedWinProbabilities, isShipVariantModalOpen } = useValues(experimentLogic({ experimentId }))
    const { closeShipVariantModal, shipVariant } = useActions(experimentLogic({ experimentId }))
    const { aggregationLabel } = useValues(groupsModel)

    const [selectedVariantKey, setSelectedVariantKey] = useState<string | null>()
    useEffect(() => setSelectedVariantKey(sortedWinProbabilities[0]?.key), [sortedWinProbabilities])

    const aggregationTargetName =
        experiment.filters.aggregation_group_type_index != null
            ? aggregationLabel(experiment.filters.aggregation_group_type_index).plural
            : 'users'

    return (
        <LemonModal
            isOpen={isShipVariantModalOpen}
            onClose={closeShipVariantModal}
            width={600}
            title="Ship a variant"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={closeShipVariantModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        // TODO: revisit if it always makes sense to stop the experiment when shipping a variant
                        // does it make sense to still *monitor* the experiment after shipping the variant?
                        onClick={() => shipVariant({ selectedVariantKey, shouldStopExperiment: true })}
                        type="primary"
                    >
                        Ship variant
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-6">
                <div className="text-sm">
                    This will roll out the selected variant to <b>100% of {aggregationTargetName}</b> and stop the
                    experiment.
                </div>
                <div className="flex items-center">
                    <div className="w-1/2 pr-4">
                        <LemonSelect
                            className="w-full"
                            data-attr="metrics-selector"
                            value={selectedVariantKey}
                            onChange={(variantKey) => setSelectedVariantKey(variantKey)}
                            options={sortedWinProbabilities.map(({ key }) => ({
                                value: key,
                                label: (
                                    <div className="space-x-2 inline-flex">
                                        <VariantTag experimentId={experimentId} variantKey={key} />
                                        {key === sortedWinProbabilities[0]?.key && (
                                            <LemonTag type="success">
                                                <b className="uppercase">Winning</b>
                                            </LemonTag>
                                        )}
                                    </div>
                                ),
                            }))}
                        />
                    </div>
                </div>
                <LemonBanner type="info" className="mb-4">
                    For more precise control over your release, adjust the rollout percentage and release conditions in
                    the{' '}
                    <Link
                        target="_blank"
                        className="font-semibold"
                        to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                    >
                        {experiment.feature_flag?.key}
                    </Link>{' '}
                    feature flag.
                </LemonBanner>
            </div>
        </LemonModal>
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
        isSingleVariantShipped,
        featureFlags,
    } = useValues(experimentLogic)

    const { archiveExperiment } = useActions(experimentLogic)

    const { aggregationLabel } = useValues(groupsModel)
    const aggregationTargetName =
        experiment.filters.aggregation_group_type_index != null
            ? aggregationLabel(experiment.filters.aggregation_group_type_index).plural
            : 'users'

    const recommendedRunningTime = experiment?.parameters?.recommended_running_time || 1
    const recommendedSampleSize = experiment?.parameters?.recommended_sample_size || 100

    if (!experiment || experimentLoading || experimentResultsLoading) {
        return <></>
    }

    if (featureFlags[FEATURE_FLAGS.EXPERIMENT_MAKE_DECISION]) {
        if (isSingleVariantShipped) {
            const shippedVariant = experiment.feature_flag?.filters.multivariate?.variants.find(
                ({ rollout_percentage }) => rollout_percentage === 100
            )
            if (!shippedVariant) {
                return <></>
            }

            return (
                <LemonBanner type="info" className="mt-4">
                    <span className="inline-flex items-center">
                        <span
                            className="border rounded px-2"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: 'var(--bg-table)' }}
                        >
                            <VariantTag experimentId={experiment.id} variantKey={shippedVariant.key} />
                        </span>
                        &nbsp; has been released to 100% of {aggregationTargetName}.
                    </span>
                </LemonBanner>
            )
        }
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

export const ResetButton = ({ experimentId }: { experimentId: number | 'new' }): JSX.Element => {
    const { experiment } = useValues(experimentLogic({ experimentId }))
    const { resetRunningExperiment } = useActions(experimentLogic)

    const onClickReset = (): void => {
        LemonDialog.open({
            title: 'Reset this experiment?',
            content: (
                <>
                    <div className="text-sm text-muted">
                        All data collected so far will be discarded and the experiment will go back to draft mode.
                    </div>
                    {experiment.archived && (
                        <div className="text-sm text-muted">Resetting will also unarchive the experiment.</div>
                    )}
                </>
            ),
            primaryButton: {
                children: 'Confirm',
                type: 'primary',
                onClick: resetRunningExperiment,
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    return (
        <LemonButton type="secondary" onClick={onClickReset}>
            Reset
        </LemonButton>
    )
}

export function StatusTag({ experiment }: { experiment: ExperimentType }): JSX.Element {
    const status = getExperimentStatus(experiment)
    return (
        <LemonTag type={getExperimentStatusColor(status)}>
            <b className="uppercase">{status}</b>
        </LemonTag>
    )
}

export function LoadingState(): JSX.Element {
    return (
        <div className="space-y-4">
            <LemonSkeleton className="w-1/3 h-4" />
            <LemonSkeleton />
            <LemonSkeleton />
            <LemonSkeleton className="w-2/3 h-4" />
        </div>
    )
}
