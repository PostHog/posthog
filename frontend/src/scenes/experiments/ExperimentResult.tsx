import { Col, Progress, Row, Skeleton, Tooltip } from 'antd'
import { useValues } from 'kea'
import { ChartDisplayType, FilterType, FunnelVizType, InsightShortId, InsightType } from '~/types'
import './Experiment.scss'
import { experimentLogic } from './experimentLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { FunnelLayout } from 'lib/constants'
import { capitalizeFirstLetter } from 'lib/utils'
import { getSeriesColor } from 'lib/colors'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { NodeKind } from '~/queries/schema'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'

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
                        <Row
                            className="border-t"
                            justify="space-between"
                            style={{
                                paddingTop: 8,
                                paddingBottom: 8,
                            }}
                        >
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
                        </Row>
                        <Row
                            className="border-t"
                            justify="space-between"
                            style={{
                                paddingTop: 8,
                                paddingBottom: 8,
                            }}
                        >
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
                        </Row>
                        <Row
                            className="border-t"
                            justify="space-between"
                            style={{
                                paddingTop: 8,
                                paddingBottom: 8,
                            }}
                        >
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
                        </Row>
                    </>
                ) : (
                    <Row justify="space-around" style={{ flexFlow: 'nowrap' }}>
                        {
                            //sort by decreasing probability
                            Object.keys(experimentResults.probability)
                                .sort((a, b) => experimentResults.probability[b] - experimentResults.probability[a])
                                .map((variant, idx) => (
                                    <Col key={idx} className="pr-4">
                                        <div>
                                            <b>{capitalizeFirstLetter(variant)}</b>
                                        </div>
                                        {experimentInsightType === InsightType.TRENDS ? (
                                            <>
                                                <Row>
                                                    <b className="pr-1">
                                                        <Row>
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
                                                        </Row>
                                                    </b>{' '}
                                                    {countDataForVariant(variant)}{' '}
                                                    {areTrendResultsConfusing && idx === 0 && (
                                                        <Tooltip
                                                            placement="right"
                                                            title="It might seem confusing that the best variant has lower absolute count, but this can happen when fewer people are exposed to this variant, so its relative count is higher."
                                                        >
                                                            <InfoCircleOutlined className="py-1 px-0.5" />
                                                        </Tooltip>
                                                    )}
                                                </Row>
                                                <div className="flex">
                                                    <b className="pr-1">Exposure:</b>{' '}
                                                    {exposureCountDataForVariant(variant)}
                                                </div>
                                            </>
                                        ) : (
                                            <Row>
                                                <b className="pr-1">Conversion rate:</b>{' '}
                                                {conversionRateForVariant(variant)}%
                                            </Row>
                                        )}
                                        <Progress
                                            percent={Number((experimentResults.probability[variant] * 100).toFixed(1))}
                                            size="small"
                                            showInfo={false}
                                            strokeColor={getSeriesColor(
                                                getIndexForVariant(variant, experimentInsightType)
                                            )}
                                        />
                                        <div>
                                            Probability that this variant is the best:{' '}
                                            <b>{(experimentResults.probability[variant] * 100).toFixed(1)}%</b>
                                        </div>
                                    </Col>
                                ))
                        }
                    </Row>
                )
            ) : (
                experimentResultsLoading && (
                    <div className="text-center">
                        <Skeleton active />
                    </div>
                )
            )}
            {experimentResults ? (
                // :KLUDGE: using `insights-page` for proper styling, should rather adapt styles
                <div className="mt-4 insights-page">
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
                        <div className="no-experiment-results">
                            {!experimentResultsLoading && (
                                <div className="text-center">
                                    <b>There are no results for this experiment yet.</b>
                                    <div className="text-sm ">
                                        {!!experimentResultCalculationError && `${experimentResultCalculationError}. `}{' '}
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
