import './Experiment.scss'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import {
    FeatureFlagGroupType,
    FunnelExperimentVariant,
    FunnelStep,
    InsightShortId,
    InsightType,
    MultivariateFlagVariant,
    TrendExperimentVariant,
} from '~/types'

import { experimentLogic } from './experimentLogic'
import { transformResultFilters } from './utils'

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
            <LemonProgress className="w-full" size="large" percent={experimentProgressPercent} />
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
    const { experimentResults, conversionRateForVariant } = useValues(experimentLogic)

    const columns: LemonTableColumns<TrendExperimentVariant | FunnelExperimentVariant> = [
        {
            className: 'w-1/3',
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
            className: 'w-1/3',
            key: 'conversionRate',
            title: 'Conversion rate',
            render: function Key(_, item): JSX.Element {
                return <div>{`${conversionRateForVariant(experimentResults, item.key)}%`}</div>
            },
        },
        {
            className: 'w-1/3',
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
    const { experimentResults } = useValues(experimentLogic)

    return (
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
            <h4>Distribution</h4>
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
            <h4>Release conditions</h4>
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
