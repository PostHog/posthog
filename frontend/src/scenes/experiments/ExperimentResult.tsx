import './Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonTable, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { FunnelLayout } from 'lib/constants'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { capitalizeFirstLetter } from 'lib/utils'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { ChartDisplayType, FilterType, FunnelVizType, InsightShortId, InsightType } from '~/types'

import { LoadingState } from './Experiment'
import { experimentLogic } from './experimentLogic'

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
        experimentResultCalculationError,
        sortedExperimentResultVariants,
        experimentMathAggregationForTrends,
    } = useValues(experimentLogic)

    const targetResults = secondaryMetricId ? secondaryMetricResults?.[secondaryMetricId] : experimentResults
    const targetResultFilters = targetResults?.filters
    const targetResultsInsightType = targetResultFilters?.insight || InsightType.TRENDS
    const targetResultsLoading = secondaryMetricId ? secondaryMetricResultsLoading : experimentResultsLoading

    const experimentResultVariants = experiment?.parameters?.feature_flag_variants || []

    return (
        <div className="experiment-result">
            {targetResults ? (
                experimentResultVariants.length > 4 ? (
                    <>
                        <LemonTable
                            showHeader={false}
                            columns={[
                                { title: 'Header', dataIndex: 'header' },
                                ...sortedExperimentResultVariants.map((variant) => ({
                                    title: capitalizeFirstLetter(variant),
                                    dataIndex: variant,
                                })),
                            ]}
                            dataSource={[
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
                                                    color: getSeriesColor(getIndexForVariant(targetResults, variant)),
                                                }}
                                            >
                                                <b>{capitalizeFirstLetter(variant)}</b>
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
                                          // TODO: Make this work better, right now empty row in middle
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
                                            targetResults.probability[variant]
                                                ? `${(targetResults.probability[variant] * 100).toFixed(1)}%`
                                                : '--',
                                        ])
                                    ),
                                },
                            ]}
                        />
                    </>
                ) : (
                    <div className="flex justify-around flex-nowrap">
                        {
                            //sort by decreasing probability, but omit the ones that are not in the results
                            sortedExperimentResultVariants
                                .filter((variant) => targetResults.probability.hasOwnProperty(variant))
                                .map((variant, idx) => (
                                    <div key={idx} className="pr-4">
                                        <div>
                                            <b>{capitalizeFirstLetter(variant)}</b>
                                        </div>
                                        {targetResultsInsightType === InsightType.TRENDS ? (
                                            <>
                                                <div className="flex">
                                                    <b className="pr-1">
                                                        <div className="flex">
                                                            {'action' in targetResults.insight[0] && (
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
                                            percent={Number((targetResults.probability[variant] * 100).toFixed(1))}
                                            strokeColor={getSeriesColor(getIndexForVariant(targetResults, variant))}
                                        />
                                        <div>
                                            Probability that this variant is the best:{' '}
                                            <b>{(targetResults.probability[variant] * 100).toFixed(1)}%</b>
                                        </div>
                                    </div>
                                ))
                        }
                    </div>
                )
            ) : (
                targetResultsLoading && <LoadingState />
            )}
            {targetResults ? (
                // :KLUDGE: using `insights-page` for proper styling, should rather adapt styles
                <div className="mt-4 Insight">
                    <Query
                        query={{
                            kind: NodeKind.InsightVizNode,
                            source: filtersToQueryNode(transformResultFilters(targetResults.filters)),
                            showTable: secondaryMetricId !== undefined ? false : true,
                            showLastComputation: true,
                            showLastComputationRefresh: false,
                        }}
                        context={{
                            insightProps: {
                                dashboardItemId: targetResults.fakeInsightId as InsightShortId,
                                cachedInsight: {
                                    short_id: targetResults.fakeInsightId as InsightShortId,
                                    filters: transformResultFilters(targetResults.filters),
                                    result: targetResults.insight,
                                    disable_baseline: true,
                                    last_refresh: targetResults.last_refresh,
                                },
                                doNotLoad: true,
                            },
                        }}
                        readOnly
                    />
                </div>
            ) : (
                experiment.start_date && (
                    <>
                        {/* TODO: Customise message for secondary metrics */}
                        <div className="no-experiment-results p-4">
                            {!targetResultsLoading && (
                                <div className="text-center">
                                    <div className="mb-4">
                                        <b>There are no results for this experiment yet.</b>
                                    </div>
                                    {!!experimentResultCalculationError && (
                                        <div className="text-sm mb-2">{experimentResultCalculationError}</div>
                                    )}
                                    <div className="text-sm ">
                                        Wait a bit longer for your users to be exposed to the experiment. Double check
                                        your feature flag implementation if you're still not seeing results.
                                    </div>
                                </div>
                            )}
                        </div>
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
