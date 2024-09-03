import '../Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'

import {
    _FunnelExperimentResults,
    _TrendsExperimentResults,
    FunnelExperimentVariant,
    InsightType,
    TrendExperimentVariant,
} from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

export function SummaryTable(): JSX.Element {
    const {
        experimentId,
        experimentResults,
        tabularExperimentResults,
        experimentInsightType,
        exposureCountDataForVariant,
        conversionRateForVariant,
        experimentMathAggregationForTrends,
        countDataForVariant,
        getHighestProbabilityVariant,
    } = useValues(experimentLogic)

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

    if (experimentInsightType === InsightType.TRENDS) {
        columns.push({
            key: 'counts',
            title: (
                <div className="flex">
                    {experimentResults.insight?.[0] && 'action' in experimentResults.insight[0] && (
                        <EntityFilterInfo filter={experimentResults.insight[0].action} />
                    )}
                    <span className="pl-1">
                        {experimentMathAggregationForTrends(experimentResults?.filters) ? 'metric' : 'count'}
                    </span>
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
                        <IconInfo className="text-muted-alt text-base" />
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

                const credibleInterval = (experimentResults as _TrendsExperimentResults)?.credible_intervals?.[
                    variant.key
                ]
                if (!credibleInterval) {
                    return <>—</>
                }

                const controlVariant = (experimentResults.variants as TrendExperimentVariant[]).find(
                    ({ key }) => key === 'control'
                ) as TrendExperimentVariant
                const controlMean = controlVariant.count / controlVariant.absolute_exposure

                // Calculate the percentage difference between the credible interval bounds of the variant and the control's mean.
                // This represents the range in which the true percentage change relative to the control is likely to fall.
                const lowerBound = ((credibleInterval[0] - controlMean) / controlMean) * 100
                const upperBound = ((credibleInterval[1] - controlMean) / controlMean) * 100

                return (
                    <div className="font-semibold">{`[${lowerBound > 0 ? '+' : ''}${lowerBound.toFixed(2)}%, ${
                        upperBound > 0 ? '+' : ''
                    }${upperBound.toFixed(2)}%]`}</div>
                )
            },
        })
    }

    if (experimentInsightType === InsightType.FUNNELS) {
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
                            <IconInfo className="text-muted-alt text-base" />
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

                    const credibleInterval = (experimentResults as _FunnelExperimentResults)?.credible_intervals?.[
                        item.key
                    ]
                    if (!credibleInterval) {
                        return <>—</>
                    }

                    const controlVariant = (experimentResults.variants as FunnelExperimentVariant[]).find(
                        ({ key }) => key === 'control'
                    ) as FunnelExperimentVariant
                    const controlConversionRate =
                        controlVariant.success_count / (controlVariant.success_count + controlVariant.failure_count)

                    if (!controlConversionRate) {
                        return <>—</>
                    }

                    // Calculate the percentage difference between the credible interval bounds of the variant and the control's conversion rate.
                    // This represents the range in which the true percentage change relative to the control is likely to fall.
                    const lowerBound = ((credibleInterval[0] - controlConversionRate) / controlConversionRate) * 100
                    const upperBound = ((credibleInterval[1] - controlConversionRate) / controlConversionRate) * 100

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
                        <span className="inline-flex items-center w-30 space-x-4">
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

    return (
        <div className="mb-4">
            <LemonTable loading={false} columns={columns} dataSource={tabularExperimentResults} />
        </div>
    )
}
