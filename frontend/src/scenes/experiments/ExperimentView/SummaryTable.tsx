import '../Experiment.scss'

import { IconInfo, IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'
import posthog from 'posthog-js'
import { urls } from 'scenes/urls'

import {
    FilterLogicalOperator,
    FunnelExperimentVariant,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    ReplayTabs,
    TrendExperimentVariant,
    UniversalFiltersGroupValue,
} from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

export function SummaryTable(): JSX.Element {
    const {
        experimentId,
        experiment,
        experimentResults,
        tabularExperimentResults,
        getMetricType,
        exposureCountDataForVariant,
        conversionRateForVariant,
        experimentMathAggregationForTrends,
        countDataForVariant,
        getHighestProbabilityVariant,
        credibleIntervalForVariant,
    } = useValues(experimentLogic)
    const metricType = getMetricType(0)

    if (!experimentResults) {
        return <></>
    }

    const winningVariant = getHighestProbabilityVariant(experimentResults)

    const columns: LemonTableColumns<TrendExperimentVariant | FunnelExperimentVariant> = [
        {
            key: 'variants',
            title: 'Variant',
            render: function Key(_, item): JSX.Element {
                return (
                    <div className="flex items-center">
                        <VariantTag experimentId={experimentId} variantKey={item.key} />
                    </div>
                )
            },
        },
    ]

    if (metricType === InsightType.TRENDS) {
        columns.push({
            key: 'counts',
            title: (
                <div className="flex">
                    {experimentResults.insight?.[0] && 'action' in experimentResults.insight[0] && (
                        <EntityFilterInfo filter={experimentResults.insight[0].action} />
                    )}
                    <span className="pl-1">{experimentMathAggregationForTrends() ? 'metric' : 'count'}</span>
                </div>
            ),
            render: function Key(_, variant): JSX.Element {
                const count = countDataForVariant(experimentResults, variant.key)
                if (!count) {
                    return <>—</>
                }

                return <div className="flex">{humanFriendlyNumber(count)}</div>
            },
        })
        columns.push({
            key: 'exposure',
            title: 'Exposure',
            render: function Key(_, variant): JSX.Element {
                const exposure = exposureCountDataForVariant(experimentResults, variant.key)
                if (!exposure) {
                    return <>—</>
                }

                return <div>{humanFriendlyNumber(exposure)}</div>
            },
        })
        columns.push({
            key: 'mean',
            title: 'Mean',
            render: function Key(_, v): JSX.Element {
                const variant = v as TrendExperimentVariant
                if (!variant.count || !variant.absolute_exposure) {
                    return <div className="font-semibold">—</div>
                }

                return <div className="font-semibold">{(variant.count / variant.absolute_exposure).toFixed(2)}</div>
            },
        })
        columns.push({
            key: 'delta',
            title: (
                <div className="inline-flex items-center space-x-1">
                    <div className="">Delta %</div>
                    <Tooltip title="Delta % indicates the percentage change in the mean between the control and the test variant.">
                        <IconInfo className="text-[var(--content-tertiary)] text-base" />
                    </Tooltip>
                </div>
            ),
            render: function Key(_, v): JSX.Element {
                const variant = v as TrendExperimentVariant

                if (variant.key === 'control') {
                    return <em>Baseline</em>
                }

                const controlVariant = (experimentResults.variants as TrendExperimentVariant[]).find(
                    ({ key }) => key === 'control'
                ) as TrendExperimentVariant

                if (
                    !variant.count ||
                    !variant.absolute_exposure ||
                    !controlVariant ||
                    !controlVariant.count ||
                    !controlVariant.absolute_exposure
                ) {
                    return <div className="font-semibold">—</div>
                }

                const controlMean = controlVariant.count / controlVariant.absolute_exposure
                const variantMean = variant.count / variant.absolute_exposure
                const delta = ((variantMean - controlMean) / controlMean) * 100

                return (
                    <div
                        className={`font-semibold ${
                            delta > 0 ? 'text-[var(--content-success)]' : delta < 0 ? 'text-danger' : ''
                        }`}
                    >{`${delta > 0 ? '+' : ''}${delta.toFixed(2)}%`}</div>
                )
            },
        })
        columns.push({
            key: 'credibleInterval',
            title: (
                <div className="inline-flex items-center space-x-1">
                    <div className="">Credible interval (95%)</div>
                    <Tooltip title="A credible interval estimates the percentage change in the mean, indicating with 95% probability how much higher or lower the test variant's mean is compared to the control.">
                        <IconInfo className="text-[var(--content-tertiary)] text-base" />
                    </Tooltip>
                </div>
            ),
            render: function Key(_, v): JSX.Element {
                const variant = v as TrendExperimentVariant
                if (variant.key === 'control') {
                    return <em>Baseline</em>
                }

                const credibleInterval = credibleIntervalForVariant(experimentResults || null, variant.key, metricType)
                if (!credibleInterval) {
                    return <>—</>
                }
                const [lowerBound, upperBound] = credibleInterval

                return (
                    <div className="font-semibold">{`[${lowerBound > 0 ? '+' : ''}${lowerBound.toFixed(2)}%, ${
                        upperBound > 0 ? '+' : ''
                    }${upperBound.toFixed(2)}%]`}</div>
                )
            },
        })
    }

    if (metricType === InsightType.FUNNELS) {
        columns.push({
            key: 'conversionRate',
            title: 'Conversion rate',
            render: function Key(_, item): JSX.Element {
                const conversionRate = conversionRateForVariant(experimentResults, item.key)
                if (!conversionRate) {
                    return <>—</>
                }

                return <div className="font-semibold">{`${conversionRate.toFixed(2)}%`}</div>
            },
        }),
            columns.push({
                key: 'delta',
                title: (
                    <div className="inline-flex items-center space-x-1">
                        <div className="">Delta %</div>
                        <Tooltip title="Delta % indicates the percentage change in the conversion rate between the control and the test variant.">
                            <IconInfo className="text-[var(--content-tertiary)] text-base" />
                        </Tooltip>
                    </div>
                ),
                render: function Key(_, item): JSX.Element {
                    if (item.key === 'control') {
                        return <em>Baseline</em>
                    }

                    const controlConversionRate = conversionRateForVariant(experimentResults, 'control')
                    const variantConversionRate = conversionRateForVariant(experimentResults, item.key)

                    if (!controlConversionRate || !variantConversionRate) {
                        return <>—</>
                    }

                    const delta = ((variantConversionRate - controlConversionRate) / controlConversionRate) * 100

                    return (
                        <div
                            className={`font-semibold ${
                                delta > 0 ? 'text-[var(--content-success)]' : delta < 0 ? 'text-danger' : ''
                            }`}
                        >{`${delta > 0 ? '+' : ''}${delta.toFixed(2)}%`}</div>
                    )
                },
            }),
            columns.push({
                key: 'credibleInterval',
                title: (
                    <div className="inline-flex items-center space-x-1">
                        <div className="">Credible interval (95%)</div>
                        <Tooltip title="A credible interval estimates the percentage change in the conversion rate, indicating with 95% probability how much higher or lower the test variant's conversion rate is compared to the control.">
                            <IconInfo className="text-[var(--content-tertiary)] text-base" />
                        </Tooltip>
                    </div>
                ),
                render: function Key(_, item): JSX.Element {
                    if (item.key === 'control') {
                        return <em>Baseline</em>
                    }

                    const credibleInterval = credibleIntervalForVariant(experimentResults || null, item.key, metricType)
                    if (!credibleInterval) {
                        return <>—</>
                    }
                    const [lowerBound, upperBound] = credibleInterval

                    return (
                        <div className="font-semibold">{`[${lowerBound > 0 ? '+' : ''}${lowerBound.toFixed(2)}%, ${
                            upperBound > 0 ? '+' : ''
                        }${upperBound.toFixed(2)}%]`}</div>
                    )
                },
            })
    }

    columns.push({
        key: 'winProbability',
        title: 'Win probability',
        sorter: (a, b) => {
            const aPercentage = (experimentResults?.probability?.[a.key] || 0) * 100
            const bPercentage = (experimentResults?.probability?.[b.key] || 0) * 100
            return aPercentage - bPercentage
        },
        render: function Key(_, item): JSX.Element {
            const variantKey = item.key
            const percentage =
                experimentResults?.probability?.[variantKey] != undefined &&
                experimentResults.probability?.[variantKey] * 100
            const isWinning = variantKey === winningVariant

            return (
                <>
                    {percentage ? (
                        <span className="inline-flex items-center w-52 space-x-4">
                            <LemonProgress className="inline-flex w-3/4" percent={percentage} />
                            <span className={`w-1/4 font-semibold ${isWinning && 'text-[var(--content-success)]'}`}>
                                {percentage.toFixed(2)}%
                            </span>
                        </span>
                    ) : (
                        '—'
                    )}
                </>
            )
        },
    })

    columns.push({
        key: 'recordings',
        title: '',
        render: function Key(_, item): JSX.Element {
            const variantKey = item.key
            return (
                <LemonButton
                    size="xsmall"
                    icon={<IconRewindPlay />}
                    tooltip="Watch recordings of people who were exposed to this variant."
                    type="secondary"
                    onClick={() => {
                        const filters: UniversalFiltersGroupValue[] = [
                            {
                                id: '$feature_flag_called',
                                name: '$feature_flag_called',
                                type: 'events',
                                properties: [
                                    {
                                        key: `$feature/${experiment.feature_flag_key}`,
                                        type: PropertyFilterType.Event,
                                        value: [variantKey],
                                        operator: PropertyOperator.Exact,
                                    },
                                    {
                                        key: `$feature/${experiment.feature_flag_key}`,
                                        type: PropertyFilterType.Event,
                                        value: 'is_set',
                                        operator: PropertyOperator.IsSet,
                                    },
                                    {
                                        key: '$feature_flag',
                                        type: PropertyFilterType.Event,
                                        value: experiment.feature_flag_key,
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                            },
                        ]
                        if (experiment.filters.insight === InsightType.FUNNELS) {
                            if (experiment.filters?.events?.[0]) {
                                filters.push(experiment.filters.events[0])
                            } else if (experiment.filters?.actions?.[0]) {
                                filters.push(experiment.filters.actions[0])
                            }
                        }
                        const filterGroup: Partial<RecordingUniversalFilters> = {
                            filter_group: {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: FilterLogicalOperator.And,
                                        values: filters,
                                    },
                                ],
                            },
                        }
                        router.actions.push(urls.replay(ReplayTabs.Home, filterGroup))
                        posthog.capture('viewed recordings from experiment', { variant: variantKey })
                    }}
                >
                    View recordings
                </LemonButton>
            )
        },
    })

    return (
        <div className="mb-4">
            <LemonTable loading={false} columns={columns} dataSource={tabularExperimentResults} />
        </div>
    )
}
