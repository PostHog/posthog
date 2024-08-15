import './Experiment.scss'

import { IconArchive, IconInfo } from '@posthog/icons'
import { LemonTable, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { FunnelLayout } from 'lib/constants'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryFromFilters } from '~/queries/nodes/InsightViz/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { ChartDisplayType, FilterType, FunnelVizType, InsightShortId, InsightType } from '~/types'

import { experimentLogic } from './experimentLogic'
import { LoadingState, NoResultsEmptyState } from './ExperimentView/components'
import { getExperimentInsightColour } from './utils'

interface ExperimentResultProps {
    secondaryMetricId?: number
}
export function ExperimentResult({ secondaryMetricId }: ExperimentResultProps): JSX.Element {
    const {
        experiment,
        experimentResults,
        secondaryMetricResults,
        countDataForVariant,
        exposureCountDataForVariant,
        experimentResultsLoading,
        secondaryMetricResultsLoading,
        conversionRateForVariant,
        getIndexForVariant,
        areTrendResultsConfusing,
        sortedExperimentResultVariants,
        experimentMathAggregationForTrends,
    } = useValues(experimentLogic)

    const isSecondaryMetric = secondaryMetricId !== undefined
    const targetResults = isSecondaryMetric ? secondaryMetricResults?.[secondaryMetricId] : experimentResults
    const targetResultFilters = targetResults?.filters
    const targetResultsInsightType = targetResultFilters?.insight || InsightType.TRENDS
    const targetResultsLoading = isSecondaryMetric ? secondaryMetricResultsLoading : experimentResultsLoading

    const experimentResultVariants = experiment?.parameters?.feature_flag_variants || []

    const validMetric = targetResults && targetResults.insight

    if (targetResultsLoading) {
        return (
            <div className="my-6">
                <LoadingState />
            </div>
        )
    }

    return (
        <div className="experiment-result">
            {validMetric &&
                (experimentResultVariants.length > 4 ? (
                    <>
                        <LemonTable
                            showHeader={false}
                            dataSource={
                                [
                                    {
                                        header: 'Variant',
                                        ...Object.fromEntries(
                                            sortedExperimentResultVariants.map((variant, idx) => [
                                                variant,
                                                <div
                                                    key={idx}
                                                    className="color"
                                                    // eslint-disable-next-line react/forbid-dom-props
                                                    style={{
                                                        color: getExperimentInsightColour(
                                                            getIndexForVariant(targetResults, variant)
                                                        ),
                                                    }}
                                                >
                                                    <b>{variant}</b>
                                                </div>,
                                            ])
                                        ),
                                    },
                                    {
                                        header:
                                            targetResultsInsightType === InsightType.TRENDS
                                                ? experimentMathAggregationForTrends(targetResultFilters)
                                                    ? 'Metric'
                                                    : 'Count'
                                                : 'Conversion Rate',
                                        ...Object.fromEntries(
                                            sortedExperimentResultVariants.map((variant) => [
                                                variant,
                                                targetResultsInsightType === InsightType.TRENDS
                                                    ? countDataForVariant(targetResults, variant)
                                                    : `${conversionRateForVariant(targetResults, variant)}%`,
                                            ])
                                        ),
                                    },
                                    targetResultsInsightType === InsightType.TRENDS
                                        ? {
                                              header: 'Exposure',
                                              ...Object.fromEntries(
                                                  sortedExperimentResultVariants.map((variant) => [
                                                      variant,
                                                      exposureCountDataForVariant(targetResults, variant),
                                                  ])
                                              ),
                                          }
                                        : {},
                                    {
                                        header: 'Probability to be the best',
                                        ...Object.fromEntries(
                                            sortedExperimentResultVariants.map((variant) => [
                                                variant,
                                                targetResults.probability?.[variant] != undefined
                                                    ? `${(targetResults.probability[variant] * 100).toFixed(1)}%`
                                                    : '--',
                                            ])
                                        ),
                                    },
                                ].filter((row) => Object.keys(row).length > 0) as {
                                    [key: string]: string | JSX.Element
                                }[]
                            }
                            columns={[
                                { title: 'Header', dataIndex: 'header' },
                                ...sortedExperimentResultVariants.map((variant) => ({
                                    title: variant,
                                    dataIndex: variant,
                                })),
                            ]}
                        />
                    </>
                ) : (
                    <div className="flex justify-around flex-nowrap">
                        {
                            //sort by decreasing probability, but omit the ones that are not in the results
                            sortedExperimentResultVariants
                                .filter(
                                    (variant) => isSecondaryMetric || targetResults.probability?.hasOwnProperty(variant)
                                )
                                .map((variant, idx) => (
                                    <div key={idx} className="pr-4">
                                        <div>
                                            <b>{variant}</b>
                                        </div>
                                        {targetResultsInsightType === InsightType.TRENDS ? (
                                            <>
                                                <div className="flex">
                                                    <b className="pr-1">
                                                        <div className="flex">
                                                            {targetResults.insight?.[0] &&
                                                                'action' in targetResults.insight[0] && (
                                                                    <EntityFilterInfo
                                                                        filter={targetResults.insight[0].action}
                                                                    />
                                                                )}
                                                            <span className="pl-1">
                                                                {experimentMathAggregationForTrends(targetResultFilters)
                                                                    ? 'metric'
                                                                    : 'count'}
                                                                :
                                                            </span>
                                                        </div>
                                                    </b>{' '}
                                                    {countDataForVariant(targetResults, variant)}{' '}
                                                    {areTrendResultsConfusing && idx === 0 && (
                                                        <Tooltip
                                                            placement="right"
                                                            title="It might seem confusing that the best variant has lower absolute count, but this can happen when fewer people are exposed to this variant, so its relative count is higher."
                                                        >
                                                            <IconInfo className="py-1 px-0.5" />
                                                        </Tooltip>
                                                    )}
                                                </div>
                                                <div className="flex">
                                                    <b className="pr-1">Exposure:</b>{' '}
                                                    {exposureCountDataForVariant(targetResults, variant)}
                                                </div>
                                            </>
                                        ) : (
                                            <div className="space-x-1">
                                                <span>
                                                    <b>Conversion rate:</b>{' '}
                                                </span>
                                                <span>{conversionRateForVariant(targetResults, variant)}%</span>
                                            </div>
                                        )}
                                        <LemonProgress
                                            percent={Number(
                                                ((targetResults.probability?.[variant] ?? 0) * 100).toFixed(1)
                                            )}
                                            strokeColor={getExperimentInsightColour(
                                                getIndexForVariant(targetResults, variant)
                                            )}
                                        />
                                        <div>
                                            Probability that this variant is the best:{' '}
                                            <b>
                                                {targetResults.probability?.[variant] != undefined
                                                    ? (targetResults.probability?.[variant] * 100).toFixed(1)
                                                    : '--'}
                                                %
                                            </b>
                                        </div>
                                    </div>
                                ))
                        }
                    </div>
                ))}
            {validMetric ? (
                // :KLUDGE: using `insights-page` for proper styling, should rather adapt styles
                <div className="mt-4 Insight">
                    <Query
                        query={{
                            kind: NodeKind.InsightVizNode,
                            source: filtersToQueryNode(transformResultFilters(targetResults.filters ?? {})),
                            showTable: !isSecondaryMetric,
                            showLastComputation: true,
                            showLastComputationRefresh: false,
                        }}
                        context={{
                            insightProps: {
                                dashboardItemId: targetResults.fakeInsightId as InsightShortId,
                                cachedInsight: {
                                    short_id: targetResults.fakeInsightId as InsightShortId,
                                    query: targetResults?.filters
                                        ? queryFromFilters(transformResultFilters(targetResults.filters))
                                        : null,
                                    result: targetResults.insight,
                                    disable_baseline: true,
                                    last_refresh: targetResults.last_refresh || null,
                                },
                                doNotLoad: true,
                            },
                        }}
                        readOnly
                    />
                </div>
            ) : (
                experiment.start_date &&
                !targetResultsLoading && (
                    <>
                        {isSecondaryMetric ? (
                            <div className="bg-bg-light pt-6 pb-8 text-muted">
                                <div className="flex flex-col items-center mx-auto space-y-2">
                                    <IconArchive className="text-secondary-3000 text-4xl" />
                                    <h2 className="text-xl font-semibold leading-tight">
                                        There are no results for this metric yet
                                    </h2>
                                </div>
                            </div>
                        ) : (
                            <NoResultsEmptyState />
                        )}
                    </>
                )
            )}
        </div>
    )
}

const transformResultFilters = (filters: Partial<FilterType>): Partial<FilterType> => ({
    ...filters,
    ...(filters.insight === InsightType.FUNNELS && {
        layout: FunnelLayout.vertical,
        funnel_viz_type: FunnelVizType.Steps,
    }),
    ...(filters.insight === InsightType.TRENDS && {
        display: ChartDisplayType.ActionsLineGraphCumulative,
    }),
})
