import './Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
// eslint-disable-next-line no-restricted-imports
import { Col } from 'antd'
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

export function ExperimentResult(): JSX.Element {
    const {
        experiment,
        secondaryColumnSpan,
        experimentResults,
        countDataForVariant,
        exposureCountDataForVariant,
        experimentInsightType,
        experimentResultsLoading,
        conversionRateForVariant,
        getIndexForVariant,
        areTrendResultsConfusing,
        experimentResultCalculationError,
        sortedExperimentResultVariants,
        experimentMathAggregationForTrends,
    } = useValues(experimentLogic)

    return (
        <div className="experiment-result">
            {experimentResults ? (
                (experiment?.parameters?.feature_flag_variants?.length || 0) > 4 ? (
                    <>
                        <div className="flex justify-between py-2 border-t">
                            <Col span={2 * secondaryColumnSpan}>Variant</Col>
                            {sortedExperimentResultVariants.map((variant, idx) => (
                                <Col
                                    key={idx}
                                    span={secondaryColumnSpan}
                                    style={{
                                        color: getSeriesColor(getIndexForVariant(variant, experimentInsightType)),
                                    }}
                                >
                                    <b>{capitalizeFirstLetter(variant)}</b>
                                </Col>
                            ))}
                        </div>
                        <div className="flex justify-between py-2 border-t">
                            <Col span={2 * secondaryColumnSpan}>
                                {experimentInsightType === InsightType.TRENDS ? 'Count' : 'Conversion Rate'}
                            </Col>
                            {sortedExperimentResultVariants.map((variant, idx) => (
                                <Col key={idx} span={secondaryColumnSpan}>
                                    {experimentInsightType === InsightType.TRENDS
                                        ? countDataForVariant(variant)
                                        : `${conversionRateForVariant(variant)}%`}
                                </Col>
                            ))}
                        </div>
                        <div className="flex justify-between py-2 border-t">
                            <Col span={2 * secondaryColumnSpan}>Exposure</Col>
                            {sortedExperimentResultVariants.map((variant, idx) => (
                                <Col key={idx} span={secondaryColumnSpan}>
                                    {exposureCountDataForVariant(variant)}
                                </Col>
                            ))}
                        </div>
                        <div className="flex justify-between py-2 border-t">
                            <Col span={2 * secondaryColumnSpan}>Probability to be the best</Col>
                            {sortedExperimentResultVariants.map((variant, idx) => (
                                <Col key={idx} span={secondaryColumnSpan}>
                                    <b>
                                        {experimentResults.probability[variant]
                                            ? `${(experimentResults.probability[variant] * 100).toFixed(1)}%`
                                            : '--'}
                                    </b>
                                </Col>
                            ))}
                        </div>
                    </>
                ) : (
                    <div className="flex justify-around flex-nowrap">
                        {
                            //sort by decreasing probability
                            Object.keys(experimentResults.probability)
                                .sort((a, b) => experimentResults.probability[b] - experimentResults.probability[a])
                                .map((variant, idx) => (
                                    <div key={idx} className="pr-4">
                                        <div>
                                            <b>{capitalizeFirstLetter(variant)}</b>
                                        </div>
                                        {experimentInsightType === InsightType.TRENDS ? (
                                            <>
                                                <div className="flex">
                                                    <b className="pr-1">
                                                        <div className="flex">
                                                            {'action' in experimentResults.insight[0] && (
                                                                <EntityFilterInfo
                                                                    filter={experimentResults.insight[0].action}
                                                                />
                                                            )}
                                                            <span className="pl-1">
                                                                {experimentMathAggregationForTrends
                                                                    ? 'metric'
                                                                    : 'count'}
                                                                :
                                                            </span>
                                                        </div>
                                                    </b>{' '}
                                                    {countDataForVariant(variant)}{' '}
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
                                                    {exposureCountDataForVariant(variant)}
                                                </div>
                                            </>
                                        ) : (
                                            <div className="space-x-1">
                                                <span>
                                                    <b>Conversion rate:</b>{' '}
                                                </span>
                                                <span>{conversionRateForVariant(variant)}%</span>
                                            </div>
                                        )}
                                        <LemonProgress
                                            percent={Number((experimentResults.probability[variant] * 100).toFixed(1))}
                                            strokeColor={getSeriesColor(
                                                getIndexForVariant(variant, experimentInsightType)
                                            )}
                                        />
                                        <div>
                                            Probability that this variant is the best:{' '}
                                            <b>{(experimentResults.probability[variant] * 100).toFixed(1)}%</b>
                                        </div>
                                    </div>
                                ))
                        }
                    </div>
                )
            ) : (
                experimentResultsLoading && <LoadingState />
            )}
            {experimentResults ? (
                // :KLUDGE: using `insights-page` for proper styling, should rather adapt styles
                <div className="mt-4 Insight">
                    <Query
                        query={{
                            kind: NodeKind.InsightVizNode,
                            source: filtersToQueryNode(transformResultFilters(experimentResults.filters)),
                            showTable: true,
                            showLastComputation: true,
                            showLastComputationRefresh: false,
                        }}
                        context={{
                            insightProps: {
                                dashboardItemId: experimentResults.fakeInsightId as InsightShortId,
                                cachedInsight: {
                                    short_id: experimentResults.fakeInsightId as InsightShortId,
                                    filters: transformResultFilters(experimentResults.filters),
                                    result: experimentResults.insight,
                                    disable_baseline: true,
                                    last_refresh: experimentResults.last_refresh,
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
