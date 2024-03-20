import '../Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { capitalizeFirstLetter } from 'lib/utils'

import { FunnelExperimentVariant, InsightType, TrendExperimentVariant } from '~/types'

import { experimentLogic } from '../experimentLogic'

export function SummaryTable(): JSX.Element {
    const {
        experimentResults,
        experimentInsightType,
        exposureCountDataForVariant,
        conversionRateForVariant,
        sortedConversionRates,
        experimentMathAggregationForTrends,
        countDataForVariant,
        areTrendResultsConfusing,
    } = useValues(experimentLogic)

    if (!experimentResults) {
        return <></>
    }

    const columns: LemonTableColumns<TrendExperimentVariant | FunnelExperimentVariant> = [
        {
            key: 'variants',
            title: 'Variant',
            render: function Key(_, item, index): JSX.Element {
                return (
                    <div className="flex items-center">
                        <div
                            className="w-2 h-2 rounded-full mr-2"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: getSeriesColor(index + 1) }}
                        />
                        <span className="font-semibold">{capitalizeFirstLetter(item.key)}</span>
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
                                <IconInfo className="py-1 px-0.5" />
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
                const isWinning = item.key === sortedConversionRates[0].key
                return (
                    <div className={`font-semibold ${isWinning && 'text-success'}`}>{`${conversionRateForVariant(
                        experimentResults,
                        item.key
                    )}%`}</div>
                )
            },
        })
    }

    columns.push({
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
                            <span className="w-1/4">{percentage.toFixed(2)}%</span>
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
            <LemonTable loading={false} columns={columns} dataSource={experimentResults?.variants || []} />
        </div>
    )
}
