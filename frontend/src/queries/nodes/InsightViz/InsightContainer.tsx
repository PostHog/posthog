import { Card, Col, Row } from 'antd'
import { InsightDisplayConfig } from './InsightDisplayConfig'
import { FunnelCanvasLabel } from 'scenes/funnels/FunnelCanvasLabel'
import {
    // ChartDisplayType,
    // ExporterFormat,
    // FunnelVizType,
    InsightType,
    ItemMode,
} from '~/types'
import { TrendInsight } from 'scenes/trends/Trends'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { PathsDataExploration } from 'scenes/paths/Paths'
import {
    // BindLogic,
    useValues,
} from 'kea'
// import { trendsLogic } from 'scenes/trends/trendsLogic'
// import { InsightsTable } from 'scenes/insights/views/InsightsTable'
import { insightLogic } from 'scenes/insights/insightLogic'
import {
    FunnelInvalidExclusionState,
    FunnelSingleStepState,
    InsightEmptyState,
    InsightErrorState,
    InsightTimeoutState,
} from 'scenes/insights/EmptyStates'
// import { funnelLogic } from 'scenes/funnels/funnelLogic'
import clsx from 'clsx'
import { PathCanvasLabel } from 'scenes/paths/PathsLabel'
import { InsightLegend, InsightLegendButton } from 'lib/components/InsightLegend/InsightLegend'
// import { Tooltip } from 'lib/lemon-ui/Tooltip'
// import { FunnelStepsTable } from './views/Funnels/FunnelStepsTable'
import { Animation } from 'lib/components/Animation/Animation'
import { AnimationType } from 'lib/animations/animations'
// import { FunnelCorrelation } from './views/Funnels/FunnelCorrelation'
// import { ExportButton } from 'lib/components/ExportButton/ExportButton'
// import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import {
    isFilterWithDisplay,
    isFunnelsFilter,
    isPathsFilter,
    // isTrendsFilter
} from 'scenes/insights/sharedUtils'
import { ComputationTimeWithRefresh } from './ComputationTimeWithRefresh'
import { FunnnelInsightDataExploration } from 'scenes/insights/views/Funnels/FunnelInsight'
import { FunnelsQuery } from '~/queries/schema'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

const VIEW_MAP = {
    [`${InsightType.TRENDS}`]: <TrendInsight view={InsightType.TRENDS} />,
    [`${InsightType.STICKINESS}`]: <TrendInsight view={InsightType.STICKINESS} />,
    [`${InsightType.LIFECYCLE}`]: <TrendInsight view={InsightType.LIFECYCLE} />,
    [`${InsightType.FUNNELS}`]: <FunnnelInsightDataExploration />,
    [`${InsightType.RETENTION}`]: <RetentionContainer />,
    [`${InsightType.PATHS}`]: <PathsDataExploration />,
}

export function InsightContainer({
    disableHeader,
    disableTable,
    // disableCorrelationTable,
    disableLastComputation,
    insightMode,
}: {
    disableHeader?: boolean
    disableTable?: boolean
    disableCorrelationTable?: boolean
    disableLastComputation?: boolean
    insightMode?: ItemMode
}): JSX.Element {
    const { insightProps, insightLoading, activeView, loadedView, filters, timedOutQueryId, erroredQueryId } =
        useValues(insightLogic)
    const { querySource } = useValues(funnelDataLogic(insightProps))
    // TODO: convert to data exploration with insightLogic
    const { areExclusionFiltersValid } = useValues(funnelLogic(insightProps))

    // TODO: implement in funnelDataLogic
    const isValidFunnel = true

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        if (activeView !== loadedView || (insightLoading && timedOutQueryId === null)) {
            return (
                <div className="text-center">
                    <Animation type={AnimationType.LaptopHog} />
                </div>
            )
        }

        // Insight specific empty states - note order is important here
        if (loadedView === InsightType.FUNNELS) {
            if (((querySource as FunnelsQuery).series || []).length <= 1) {
                return <FunnelSingleStepState actionable={insightMode === ItemMode.Edit || disableTable} />
            }
            if (!areExclusionFiltersValid) {
                return <FunnelInvalidExclusionState />
            }
            if (!isValidFunnel && !insightLoading) {
                return <InsightEmptyState />
            }
        }

        // Insight agnostic empty states
        if (!!erroredQueryId) {
            return <InsightErrorState queryId={erroredQueryId} />
        }
        if (!!timedOutQueryId) {
            return <InsightTimeoutState isLoading={insightLoading} queryId={timedOutQueryId} />
        }

        return null
    })()

    return (
        <>
            {/* These are filters that are reused between insight features. They each have generic logic that updates the url */}
            <Card
                title={disableHeader ? null : <InsightDisplayConfig disableTable={!!disableTable} />}
                data-attr="insights-graph"
                className="insights-graph-container"
            >
                <div>
                    <div
                        className={clsx('flex items-center justify-between insights-graph-header', {
                            funnels: isFunnelsFilter(filters),
                        })}
                    >
                        {/*Don't add more than two columns in this row.*/}
                        {!disableLastComputation && (
                            <div>
                                <ComputationTimeWithRefresh />
                            </div>
                        )}
                        <div>
                            {isFunnelsFilter(filters) ? <FunnelCanvasLabel /> : null}
                            {isPathsFilter(filters) ? <PathCanvasLabel /> : null}
                            <InsightLegendButton />
                        </div>
                    </div>
                    {!!BlockingEmptyState ? (
                        BlockingEmptyState
                    ) : isFilterWithDisplay(filters) && filters.show_legend ? (
                        <Row className="insights-graph-container-row" wrap={false}>
                            <Col className="insights-graph-container-row-left">{VIEW_MAP[activeView]}</Col>
                            <Col className="insights-graph-container-row-right">
                                <InsightLegend />
                            </Col>
                        </Row>
                    ) : (
                        VIEW_MAP[activeView]
                    )}
                </div>
            </Card>
        </>
    )
}
