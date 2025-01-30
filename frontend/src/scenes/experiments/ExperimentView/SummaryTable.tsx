import { IconInfo, IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'
import posthog from 'posthog-js'
import { urls } from 'scenes/urls'

import { ExperimentFunnelsQuery, ExperimentTrendsQuery, NodeKind } from '~/queries/schema'
import {
    FilterLogicalOperator,
    InsightType,
    RecordingUniversalFilters,
    ReplayTabs,
    TrendExperimentVariant,
} from '~/types'

import { experimentLogic } from '../experimentLogic'
import { getViewRecordingFilters } from '../utils'
import { VariantTag } from './components'

export function SummaryTable({
    metric,
    metricIndex = 0,
    isSecondary = false,
}: {
    metric: ExperimentTrendsQuery | ExperimentFunnelsQuery
    metricIndex?: number
    isSecondary?: boolean
}): JSX.Element {
    const {
        experimentId,
        experiment,
        metricResults,
        secondaryMetricResults,
        tabularExperimentResults,
        getMetricType,
        exposureCountDataForVariant,
        conversionRateForVariant,
        experimentMathAggregationForTrends,
        countDataForVariant,
        getHighestProbabilityVariant,
        credibleIntervalForVariant,
    } = useValues(experimentLogic)
    const metricType = getMetricType(metric)
    const result = isSecondary ? secondaryMetricResults?.[metricIndex] : metricResults?.[metricIndex]
    if (!result) {
        return <></>
    }

    const winningVariant = getHighestProbabilityVariant(result)

    const columns: LemonTableColumns<any> = [
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
                    {result.insight?.[0] && 'action' in result.insight[0] && (
                        <EntityFilterInfo filter={result.insight[0].action} />
                    )}
                    <span className="pl-1">{experimentMathAggregationForTrends() ? 'metric' : 'count'}</span>
                </div>
            ),
            render: function Key(_, variant): JSX.Element {
                const count = countDataForVariant(result, variant.key)
                if (!count) {
                    return <>—</>
                }

                return <div className="flex">{humanFriendlyNumber(count)}</div>
            },
        })
        columns.push({
            key: 'exposure',
            title: (
                <div className="inline-flex items-center space-x-1">
                    <div className="">Exposure</div>
                    <Tooltip
                        title={
                            <div>
                                The number of users who were exposed to this variant. By default, this is measured by
                                the count of <LemonTag type="option">$feature_flag_called</LemonTag> events per unique
                                user. Check your metric settings to confirm how this is measured.
                            </div>
                        }
                    >
                        <IconInfo className="text-muted-alt text-base" />
                    </Tooltip>
                </div>
            ),
            render: function Key(_, variant): JSX.Element {
                const exposure = exposureCountDataForVariant(result, variant.key)
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
                        <IconInfo className="text-muted-alt text-base" />
                    </Tooltip>
                </div>
            ),
            render: function Key(_, v): JSX.Element {
                const variant = v as TrendExperimentVariant

                if (variant.key === 'control') {
                    return <em>Baseline</em>
                }

                const controlVariant = (result.variants as TrendExperimentVariant[]).find(
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
                    <div className={`font-semibold ${delta > 0 ? 'text-success' : delta < 0 ? 'text-danger' : ''}`}>{`${
                        delta > 0 ? '+' : ''
                    }${delta.toFixed(2)}%`}</div>
                )
            },
        })
        columns.push({
            key: 'credibleInterval',
            title: (
                <div className="inline-flex items-center space-x-1">
                    <div className="">Credible interval (95%)</div>
                    <Tooltip title="A credible interval estimates the percentage change in the mean, indicating with 95% probability how much higher or lower the test variant's mean is compared to the control.">
                        <IconInfo className="text-muted-alt text-base" />
                    </Tooltip>
                </div>
            ),
            render: function Key(_, v): JSX.Element {
                const variant = v as TrendExperimentVariant
                if (variant.key === 'control') {
                    return <em>Baseline</em>
                }

                const credibleInterval = credibleIntervalForVariant(result || null, variant.key, metricType)
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
                const conversionRate = conversionRateForVariant(result, item.key)
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
                            <IconInfo className="text-muted-alt text-base" />
                        </Tooltip>
                    </div>
                ),
                render: function Key(_, item): JSX.Element {
                    if (item.key === 'control') {
                        return <em>Baseline</em>
                    }

                    const controlConversionRate = conversionRateForVariant(result, 'control')
                    const variantConversionRate = conversionRateForVariant(result, item.key)

                    if (!controlConversionRate || !variantConversionRate) {
                        return <>—</>
                    }

                    const delta = ((variantConversionRate - controlConversionRate) / controlConversionRate) * 100

                    return (
                        <div
                            className={`font-semibold ${delta > 0 ? 'text-success' : delta < 0 ? 'text-danger' : ''}`}
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
                            <IconInfo className="text-muted-alt text-base" />
                        </Tooltip>
                    </div>
                ),
                render: function Key(_, item): JSX.Element {
                    if (item.key === 'control') {
                        return <em>Baseline</em>
                    }

                    const credibleInterval = credibleIntervalForVariant(result || null, item.key, metricType)
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
            const aPercentage = (result?.probability?.[a.key] || 0) * 100
            const bPercentage = (result?.probability?.[b.key] || 0) * 100
            return aPercentage - bPercentage
        },
        render: function Key(_, item): JSX.Element {
            const variantKey = item.key
            const percentage = result?.probability?.[variantKey] != undefined && result.probability?.[variantKey] * 100
            const isWinning = variantKey === winningVariant

            return (
                <>
                    {percentage ? (
                        <span className="inline-flex items-center w-52 space-x-4">
                            <LemonProgress className="inline-flex w-3/4" percent={percentage} />
                            <span className={`w-1/4 font-semibold ${isWinning && 'text-success'}`}>
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

            const filters = getViewRecordingFilters(metric, experiment.feature_flag_key, variantKey)
            return (
                <LemonButton
                    size="xsmall"
                    icon={<IconRewindPlay />}
                    tooltip="Watch recordings of people who were exposed to this variant."
                    disabledReason={filters.length === 0 ? 'Unable to identify recordings for this metric' : undefined}
                    type="secondary"
                    onClick={() => {
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
                            date_from: experiment?.start_date,
                            date_to: experiment?.end_date,
                            filter_test_accounts:
                                metric.kind === NodeKind.ExperimentTrendsQuery
                                    ? metric.count_query.filterTestAccounts
                                    : metric.funnels_query.filterTestAccounts,
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
            <LemonTable
                loading={false}
                columns={columns}
                dataSource={tabularExperimentResults(metricIndex, isSecondary)}
            />
        </div>
    )
}
