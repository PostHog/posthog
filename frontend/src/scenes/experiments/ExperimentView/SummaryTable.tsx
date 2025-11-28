import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconInfo, IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    FunnelExperimentVariant,
    InsightType,
    RecordingUniversalFilters,
    ReplayTabs,
    TrendExperimentVariant,
} from '~/types'

import { experimentLogic } from '../experimentLogic'
import {
    calculateDelta,
    conversionRateForVariant,
    countDataForVariant,
    credibleIntervalForVariant,
    exposureCountDataForVariant,
    getHighestProbabilityVariant,
} from '../legacyExperimentCalculations'
import { getViewRecordingFilters, getViewRecordingFiltersLegacy, isLegacyExperimentQuery } from '../utils'
import { VariantTag } from './components'

export function SummaryTable({
    metric,
    displayOrder = 0,
    isSecondary = false,
}: {
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    displayOrder?: number
    isSecondary?: boolean
}): JSX.Element {
    const {
        experiment,
        legacyPrimaryMetricsResults,
        legacySecondaryMetricsResults,
        tabularExperimentResults,
        getInsightType,
        experimentMathAggregationForTrends,
    } = useValues(experimentLogic)
    const insightType = getInsightType(metric)
    const result = isSecondary
        ? legacySecondaryMetricsResults?.[displayOrder]
        : legacyPrimaryMetricsResults?.[displayOrder]
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
                        <VariantTag variantKey={item.key} />
                    </div>
                )
            },
        },
    ]

    if (insightType === InsightType.TRENDS) {
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
                <div className="inline-flex items-center deprecated-space-x-1">
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
                        <IconInfo className="text-secondary text-base" />
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
                <div className="inline-flex items-center deprecated-space-x-1">
                    <div className="">Delta %</div>
                    <Tooltip title="Delta % indicates the percentage change in the mean between the control and the test variant.">
                        <IconInfo className="text-secondary text-base" />
                    </Tooltip>
                </div>
            ),
            render: function Key(_, v): JSX.Element {
                const variant = v as TrendExperimentVariant

                if (variant.key === 'control') {
                    return <em>Baseline</em>
                }

                const deltaResult = calculateDelta(result, variant.key, insightType)
                if (!deltaResult) {
                    return <div className="font-semibold">—</div>
                }

                return (
                    <div
                        className={`font-semibold ${
                            deltaResult.isPositive ? 'text-success' : deltaResult.deltaPercent < 0 ? 'text-danger' : ''
                        }`}
                    >
                        {`${deltaResult.isPositive ? '+' : ''}${deltaResult.deltaPercent.toFixed(2)}%`}
                    </div>
                )
            },
        })
        columns.push({
            key: 'credibleInterval',
            title: (
                <div className="inline-flex items-center deprecated-space-x-1">
                    <div className="">Credible interval (95%)</div>
                    <Tooltip title="A credible interval estimates the percentage change in the mean, indicating with 95% probability how much higher or lower the test variant's mean is compared to the control.">
                        <IconInfo className="text-secondary text-base" />
                    </Tooltip>
                </div>
            ),
            render: function Key(_, v): JSX.Element {
                const variant = v as TrendExperimentVariant
                if (variant.key === 'control') {
                    return <em>Baseline</em>
                }

                const credibleInterval = credibleIntervalForVariant(result || null, variant.key, insightType)
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

    if (insightType === InsightType.FUNNELS) {
        // NOTE: For funnel metrics on the new engine, we show exposures and converted counts in the table,
        // as we don't yet have the detailed view as we do for the legacy funnel metrics.
        if (metric.kind === NodeKind.ExperimentMetric) {
            columns.push({
                key: 'exposures',
                title: 'Exposures',
                render: function Key(_, item): JSX.Element {
                    const variant = item as FunnelExperimentVariant
                    const exposures = variant.success_count + variant.failure_count
                    if (!exposures) {
                        return <>—</>
                    }

                    return <div className="font-semibold">{humanFriendlyNumber(exposures)}</div>
                },
            })
            columns.push({
                key: 'converted',
                title: 'Converted',
                render: function Key(_, item): JSX.Element {
                    const variant = item as FunnelExperimentVariant
                    const converted = variant.success_count
                    if (!converted) {
                        return <>—</>
                    }

                    return <div className="font-semibold">{humanFriendlyNumber(converted)}</div>
                },
            })
        }

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
        })

        columns.push({
            key: 'delta',
            title: (
                <div className="inline-flex items-center deprecated-space-x-1">
                    <div className="">Delta %</div>
                    <Tooltip title="Delta % indicates the percentage change in the conversion rate between the control and the test variant.">
                        <IconInfo className="text-secondary text-base" />
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
                    <div className={`font-semibold ${delta > 0 ? 'text-success' : delta < 0 ? 'text-danger' : ''}`}>{`${
                        delta > 0 ? '+' : ''
                    }${delta.toFixed(2)}%`}</div>
                )
            },
        })

        columns.push({
            key: 'credibleInterval',
            title: (
                <div className="inline-flex items-center deprecated-space-x-1">
                    <div className="">Credible interval (95%)</div>
                    <Tooltip title="A credible interval estimates the percentage change in the conversion rate, indicating with 95% probability how much higher or lower the test variant's conversion rate is compared to the control.">
                        <IconInfo className="text-secondary text-base" />
                    </Tooltip>
                </div>
            ),
            render: function Key(_, item): JSX.Element {
                if (item.key === 'control') {
                    return <em>Baseline</em>
                }

                const credibleInterval = credibleIntervalForVariant(result || null, item.key, insightType)
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
            const percentage = result?.probability?.[variantKey] !== undefined && result.probability?.[variantKey] * 100
            const isWinning = variantKey === winningVariant

            // Only show the win probability if the conversion rate exists
            // TODO: move this to the backend
            const conversionRate = conversionRateForVariant(result, variantKey)
            const hasValidConversionRate = conversionRate !== null && conversionRate !== undefined

            return (
                <>
                    {percentage && (insightType === InsightType.FUNNELS ? hasValidConversionRate : true) ? (
                        <span className="inline-flex items-center w-52 deprecated-space-x-4">
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

            const filters = isLegacyExperimentQuery(metric)
                ? getViewRecordingFiltersLegacy(metric, experiment.feature_flag_key, variantKey)
                : getViewRecordingFilters(experiment, metric, variantKey)

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
                                metric.kind === NodeKind.ExperimentMetric
                                    ? (experiment.exposure_criteria?.filterTestAccounts ?? false)
                                    : metric.kind === NodeKind.ExperimentTrendsQuery
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
                dataSource={tabularExperimentResults(displayOrder, isSecondary)}
            />
        </div>
    )
}
