import './Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, LemonTable, LemonTableColumns, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { urls } from 'scenes/urls'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import {
    Experiment,
    FeatureFlagGroupType,
    FunnelExperimentVariant,
    FunnelStep,
    InsightShortId,
    InsightType,
    MultivariateFlagVariant,
    TrendExperimentVariant,
} from '~/types'

import { EXPERIMENT_EXPOSURE_INSIGHT_ID, EXPERIMENT_INSIGHT_ID } from './constants'
import { experimentLogic } from './experimentLogic'
import { MetricDisplay } from './ExperimentPreview'
import { MetricSelector } from './MetricSelector'
import { transformResultFilters } from './utils'

export function ExperimentStatus(): JSX.Element {
    const { sortedConversionRates } = useValues(experimentLogic)

    const winningVariant = sortedConversionRates[0]
    const secondBestVariant = sortedConversionRates[1]
    const difference = winningVariant.conversionRate - secondBestVariant.conversionRate

    return (
        <div>
            <h2 className="font-semibold text-lg">Status</h2>
            <LemonDivider />
            <div className="items-center inline-flex">
                <div
                    className="w-2 h-2 rounded-full mr-1"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: getSeriesColor(winningVariant.index + 1) }}
                />
                <span className="font-semibold">{capitalizeFirstLetter(winningVariant.key)}</span>
                &nbsp;
                <span>is winning with a</span>
                &nbsp;
                <span className="font-semibold text-success items-center">{`${difference}% lift`}</span>
                &nbsp;
                <span>in conversion rate (vs</span>
                &nbsp;
                <div
                    className="w-2 h-2 rounded-full mr-1"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        backgroundColor: getSeriesColor(secondBestVariant.index + 1),
                    }}
                />
                <span className="font-semibold">{capitalizeFirstLetter(secondBestVariant.key)}</span>
                <span>)</span>
            </div>
        </div>
    )
}

export function ExperimentProgressBar(): JSX.Element {
    const { experiment, experimentResults, experimentInsightType } = useValues(experimentLogic)

    // Parameters for experiment results
    // don't use creation variables in results
    const funnelResultsPersonsTotal =
        experimentInsightType === InsightType.FUNNELS && experimentResults?.insight
            ? (experimentResults.insight as FunnelStep[][]).reduce(
                  (sum: number, variantResult: FunnelStep[]) => variantResult[0]?.count + sum,
                  0
              )
            : 0

    const experimentProgressPercent =
        experimentInsightType === InsightType.FUNNELS
            ? ((funnelResultsPersonsTotal || 0) / (experiment?.parameters?.recommended_sample_size || 1)) * 100
            : (dayjs().diff(experiment?.start_date, 'day') / (experiment?.parameters?.recommended_running_time || 1)) *
              100

    return (
        <div>
            <div className="mb-1 font-semibold">{`${
                experimentProgressPercent > 100 ? 100 : experimentProgressPercent
            }% complete`}</div>
            <LemonProgress
                className="w-full border"
                bgColor="var(--bg-table)"
                size="large"
                percent={experimentProgressPercent}
            />
            {experimentInsightType === InsightType.TRENDS && experiment.start_date && (
                <div className="flex justify-between mt-2">
                    {experiment.end_date ? (
                        <div>
                            Ran for <b>{dayjs(experiment.end_date).diff(experiment.start_date, 'day')}</b> days
                        </div>
                    ) : (
                        <div>
                            <b>{dayjs().diff(experiment.start_date, 'day')}</b> days running
                        </div>
                    )}
                    <div>
                        Goal: <b>{experiment?.parameters?.recommended_running_time ?? 'Unknown'}</b> days
                    </div>
                </div>
            )}
            {experimentInsightType === InsightType.FUNNELS && (
                <div className="flex justify-between mt-2">
                    {experiment.end_date ? (
                        <div>
                            Saw <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b> participants
                        </div>
                    ) : (
                        <div>
                            <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b> participants seen
                        </div>
                    )}
                    <div>
                        Goal: <b>{humanFriendlyNumber(experiment?.parameters?.recommended_sample_size || 0)}</b>{' '}
                        participants
                    </div>
                </div>
            )}
        </div>
    )
}

export function SummaryTable(): JSX.Element {
    const { experimentResults, conversionRateForVariant, sortedConversionRates } = useValues(experimentLogic)

    const columns: LemonTableColumns<TrendExperimentVariant | FunnelExperimentVariant> = [
        {
            className: 'w-1/4',
            key: 'variants',
            title: 'Variant',
            render: function Key(_, item, index): JSX.Element {
                return (
                    <div className="flex items-center">
                        <div
                            className="w-2 h-2 bg-blue-500 rounded-full mr-2"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: getSeriesColor(index + 1) }}
                        />
                        <span className="font-semibold">{capitalizeFirstLetter(item.key)}</span>
                    </div>
                )
            },
        },
        {
            className: 'w-1/4',
            key: 'conversionRate',
            title: 'Conversion rate',
            render: function Key(_, item): JSX.Element {
                const isWinning = item.key === sortedConversionRates[0].key
                return (
                    <div className={`font-semibold ${isWinning && 'text-success'}`}>{`${conversionRateForVariant(
                        experimentResults,
                        item.key
                    )}%`}</div>
                )
            },
        },
        {
            className: 'w-1/4',
            key: 'winProbability',
            title: 'Win probability',
            render: function Key(_, item): JSX.Element {
                const percentage =
                    experimentResults?.probability?.[item.key] != undefined &&
                    experimentResults.probability?.[item.key] * 100

                return (
                    <>
                        {percentage ? (
                            <span className="inline-flex items-center w-30 space-x-4">
                                <LemonProgress className="inline-flex w-3/4" percent={percentage} />
                                <span className="w-1/4">{percentage.toFixed(1)}%</span>
                            </span>
                        ) : (
                            '--'
                        )}
                    </>
                )
            },
        },
    ]
    return <LemonTable loading={false} columns={columns} dataSource={experimentResults?.variants || []} />
}

export function QueryViz(): JSX.Element {
    const { experiment, experimentId, experimentResults, experimentInsightType, experimentMathAggregationForTrends } =
        useValues(experimentLogic)
    const { openExperimentGoalModal } = useActions(experimentLogic({ experimentId }))

    return (
        <div>
            <div className="flex">
                <div className="w-1/2">
                    {experimentInsightType === InsightType.TRENDS &&
                        !experimentMathAggregationForTrends(experiment.filters) && (
                            <ExposureMetric experimentId={experimentId} />
                        )}
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="mt-auto ml-auto">
                        <LemonButton className="mb-2 ml-auto" type="secondary" onClick={openExperimentGoalModal}>
                            Change experiment goal
                        </LemonButton>
                    </div>
                </div>
            </div>
            <Query
                query={{
                    kind: NodeKind.InsightVizNode,
                    source: filtersToQueryNode(transformResultFilters(experimentResults?.filters ?? {})),
                    showTable: true,
                    showLastComputation: true,
                    showLastComputationRefresh: false,
                }}
                context={{
                    insightProps: {
                        dashboardItemId: experimentResults?.fakeInsightId as InsightShortId,
                        cachedInsight: {
                            short_id: experimentResults?.fakeInsightId as InsightShortId,
                            filters: transformResultFilters(experimentResults?.filters ?? {}),
                            result: experimentResults?.insight,
                            disable_baseline: true,
                            last_refresh: experimentResults?.last_refresh,
                        },
                        doNotLoad: true,
                    },
                }}
                readOnly
            />
        </div>
    )
}

export function DistributionTable(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    const columns: LemonTableColumns<MultivariateFlagVariant> = [
        {
            className: 'w-1/3',
            key: 'key',
            title: 'Variant',
            render: function Key(_, item, index): JSX.Element {
                return (
                    <div className="flex items-center">
                        <div
                            className="w-2 h-2 bg-blue-500 rounded-full mr-2"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: getSeriesColor(index + 1) }}
                        />
                        <span className="font-semibold">{capitalizeFirstLetter(item.key)}</span>
                    </div>
                )
            },
        },
        {
            className: 'w-1/3',
            key: 'rollout_percentage',
            title: 'Rollout',
            render: function Key(_, item): JSX.Element {
                return <div>{`${item.rollout_percentage}%`}</div>
            },
        },
    ]

    return (
        <div>
            <div className="flex">
                <div className="w-1/2">
                    <h2 className="font-semibold text-lg">Distribution</h2>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto mb-2">
                        <Link
                            className="font-semibold"
                            to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                        >
                            Manage distribution
                        </Link>
                    </div>
                </div>
            </div>
            <LemonTable loading={false} columns={columns} dataSource={experiment.parameters.feature_flag_variants} />
        </div>
    )
}

export function ReleaseConditionsTable(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    const columns: LemonTableColumns<FeatureFlagGroupType> = [
        {
            className: 'w-1/3',
            key: 'key',
            title: '',
            render: function Key(_, item, index): JSX.Element {
                return <div className="font-semibold">{`Set ${index + 1}`}</div>
            },
        },
        {
            className: 'w-1/3',
            key: 'rollout_percentage',
            title: 'Rollout',
            render: function Key(_, item): JSX.Element {
                // const aggregationTargetName =
                // aggregationLabel && filters.aggregation_group_type_index != null
                //     ? aggregationLabel(filters.aggregation_group_type_index).plural
                //     : 'users'

                return <div>{`${item.rollout_percentage}% of`}</div>
            },
        },
    ]

    return (
        <div>
            <div className="flex">
                <div className="w-1/2">
                    <h2 className="font-semibold text-lg">Release conditions</h2>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto mb-2">
                        <Link
                            className="font-semibold"
                            to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                        >
                            Manage release conditions
                        </Link>
                    </div>
                </div>
            </div>
            <LemonTable loading={false} columns={columns} dataSource={experiment.feature_flag?.filters.groups || []} />
        </div>
    )
}

export function NoResultsEmptyState(): JSX.Element {
    const { experimentResultsLoading, experimentResultCalculationError } = useValues(experimentLogic)

    return (
        <div className="no-experiment-results p-4">
            {!experimentResultsLoading && (
                <div className="text-center">
                    <div className="mb-4">
                        <b>There are no results for this experiment yet.</b>
                    </div>
                    {!!experimentResultCalculationError && (
                        <div className="text-sm mb-2">{experimentResultCalculationError}</div>
                    )}
                    <div className="text-sm ">
                        Wait a bit longer for your users to be exposed to the experiment. Double check your feature flag
                        implementation if you're still not seeing results.
                    </div>
                </div>
            )}
        </div>
    )
}

export function ExposureMetric({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment } = useValues(experimentLogic({ experimentId }))
    const { openExperimentExposureModal, updateExperimentExposure } = useActions(experimentLogic({ experimentId }))

    return (
        <>
            <div className="card-secondary mb-2 mt-4">
                Exposure metric
                <Tooltip
                    title={`This metric determines how we calculate exposure for the experiment. Only users who have this event alongside the property '$feature/${experiment.feature_flag_key}' are included in the exposure calculations.`}
                >
                    <IconInfo className="ml-1 text-muted text-sm" />
                </Tooltip>
            </div>
            {experiment.parameters?.custom_exposure_filter ? (
                <MetricDisplay filters={experiment.parameters.custom_exposure_filter} />
            ) : (
                <span className="description">Default via $feature_flag_called events</span>
            )}
            <div className="mb-2 mt-2">
                <span className="flex">
                    <LemonButton type="secondary" size="small" onClick={openExperimentExposureModal} className="mr-2">
                        Change exposure metric
                    </LemonButton>
                    {experiment.parameters?.custom_exposure_filter && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="small"
                            className="mr-2"
                            onClick={() => updateExperimentExposure(null)}
                        >
                            Reset exposure
                        </LemonButton>
                    )}
                </span>
            </div>
        </>
    )
}

export function ExperimentGoalModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isExperimentGoalModalOpen, experimentLoading } = useValues(experimentLogic({ experimentId }))
    const { closeExperimentGoalModal, updateExperimentGoal, setNewExperimentInsight } = useActions(
        experimentLogic({ experimentId })
    )

    return (
        <LemonModal
            isOpen={isExperimentGoalModalOpen}
            onClose={closeExperimentGoalModal}
            width={1000}
            title="Change experiment goal"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton form="edit-experiment-goal-form" type="secondary" onClick={closeExperimentGoalModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-goal-form"
                        onClick={() => {
                            updateExperimentGoal(experiment.filters)
                        }}
                        type="primary"
                        loading={experimentLoading}
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <Form
                logic={experimentLogic}
                props={{ experimentId }}
                formKey="experiment"
                id="edit-experiment-goal-form"
                className="space-y-4"
            >
                <Field name="filters">
                    <MetricSelector
                        dashboardItemId={EXPERIMENT_INSIGHT_ID}
                        setPreviewInsight={setNewExperimentInsight}
                        showDateRangeBanner
                    />
                </Field>
            </Form>
        </LemonModal>
    )
}

export function ExperimentExposureModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isExperimentExposureModalOpen, experimentLoading } = useValues(
        experimentLogic({ experimentId })
    )
    const { closeExperimentExposureModal, updateExperimentExposure, setExperimentExposureInsight } = useActions(
        experimentLogic({ experimentId })
    )

    return (
        <LemonModal
            isOpen={isExperimentExposureModalOpen}
            onClose={closeExperimentExposureModal}
            width={1000}
            title="Change experiment exposure"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        type="secondary"
                        onClick={closeExperimentExposureModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            if (experiment.parameters.custom_exposure_filter) {
                                updateExperimentExposure(experiment.parameters.custom_exposure_filter)
                            }
                        }}
                        type="primary"
                        loading={experimentLoading}
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <Form
                logic={experimentLogic}
                props={{ experimentId }}
                formKey="experiment"
                id="edit-experiment-exposure-form"
                className="space-y-4"
            >
                <Field name="filters">
                    <MetricSelector
                        dashboardItemId={EXPERIMENT_EXPOSURE_INSIGHT_ID}
                        setPreviewInsight={setExperimentExposureInsight}
                    />
                </Field>
            </Form>
        </LemonModal>
    )
}
