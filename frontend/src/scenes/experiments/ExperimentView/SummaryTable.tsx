import '../Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { FunnelExperimentVariant, InsightType, TrendExperimentVariant } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

export function SummaryTable(): JSX.Element {
    const {
        experimentResults,
        tabularExperimentResults,
        experimentInsightType,
        exposureCountDataForVariant,
        conversionRateForVariant,
        experimentMathAggregationForTrends,
        countDataForVariant,
        areTrendResultsConfusing,
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
                        <VariantTag variantKey={item.key} />
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
            render: function Key(_, item, index): JSX.Element {
                return (
                    <div className="flex">
                        {countDataForVariant(experimentResults, item.key)}{' '}
                        {areTrendResultsConfusing && index === 0 && (
                            <Tooltip
                                placement="right"
                                title="It might seem confusing that the best variant has lower absolute count, but this can happen when fewer people are exposed to this variant, so its relative count is higher."
                            >
                                <IconInfo className="py-1 px-0.5 text-lg" />
                            </Tooltip>
                        )}
                    </div>
                )
            },
        })
        columns.push({
            key: 'exposure',
            title: 'Exposure',
            render: function Key(_, item): JSX.Element {
                return <div>{exposureCountDataForVariant(experimentResults, item.key)}</div>
            },
        })
    }

    if (experimentInsightType === InsightType.FUNNELS) {
        columns.push({
            key: 'conversionRate',
            title: 'Conversion rate',
            render: function Key(_, item): JSX.Element {
                const conversionRate = conversionRateForVariant(experimentResults, item.key)
                return (
                    <div className="font-semibold">
                        {conversionRate === '--' ? conversionRate : `${conversionRate}%`}
                    </div>
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
                        '--'
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
