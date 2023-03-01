import { Card, Col, Row } from 'antd'
import { InsightDisplayConfig } from './InsightDisplayConfig'
import { FunnelCanvasLabel } from 'scenes/funnels/FunnelCanvasLabel'
import { ChartDisplayType, FunnelVizType, ExporterFormat, InsightType, ItemMode } from '~/types'
import { TrendInsight } from 'scenes/trends/Trends'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { PathsDataExploration } from 'scenes/paths/Paths'
import { useValues } from 'kea'
import { InsightsTableDataExploration } from 'scenes/insights/views/InsightsTable/InsightsTable'
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
import { Tooltip } from 'lib/lemon-ui/Tooltip'
// import { FunnelStepsTable } from './views/Funnels/FunnelStepsTable'
import { Animation } from 'lib/components/Animation/Animation'
import { AnimationType } from 'lib/animations/animations'
// import { FunnelCorrelation } from './views/Funnels/FunnelCorrelation'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
// import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { ComputationTimeWithRefresh } from './ComputationTimeWithRefresh'
import { FunnelInsightDataExploration } from 'scenes/insights/views/Funnels/FunnelInsight'
import { FunnelsQuery, StickinessFilter, TrendsFilter } from '~/queries/schema'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'

const VIEW_MAP = {
    [`${InsightType.TRENDS}`]: <TrendInsight view={InsightType.TRENDS} />,
    [`${InsightType.STICKINESS}`]: <TrendInsight view={InsightType.STICKINESS} />,
    [`${InsightType.LIFECYCLE}`]: <TrendInsight view={InsightType.LIFECYCLE} />,
    [`${InsightType.FUNNELS}`]: <FunnelInsightDataExploration />,
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
    const {
        insightProps,
        canEditInsight,
        insightLoading,
        timedOutQueryId,
        erroredQueryId,
        // isUsingSessionAnalysis,
    } = useValues(insightLogic)

    const { activeView } = useValues(insightNavLogic(insightProps))

    // const {
    //     areFiltersValid,
    //     isValidFunnel,
    //     areExclusionFiltersValid,
    //     // correlationAnalysisAvailable
    // } = useValues(funnelLogic(insightProps))
    const { querySource } = useValues(funnelDataLogic(insightProps))
    // TODO: convert to data exploration with insightLogic
    const { areExclusionFiltersValid } = useValues(funnelLogic(insightProps))
    const {
        isTrends,
        isFunnels,
        isPaths,
        display,
        trendsFilter,
        funnelsFilter,
        supportsDisplay,
        insightFilter,
        exportContext,
    } = useValues(insightDataLogic(insightProps))

    // TODO: implement in funnelDataLogic
    const isValidFunnel = true
    const areFiltersValid = true

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        if (insightLoading && timedOutQueryId === null) {
            return (
                <div className="text-center">
                    <Animation type={AnimationType.LaptopHog} />
                </div>
            )
        }

        // Insight specific empty states - note order is important here
        if (activeView === InsightType.FUNNELS) {
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
            return (
                <InsightTimeoutState
                    isLoading={insightLoading}
                    queryId={timedOutQueryId}
                    insightProps={insightProps}
                    insightType={activeView}
                />
            )
        }

        return null
    })()

    function renderTable(): JSX.Element | null {
        if (
            isFunnels &&
            erroredQueryId === null &&
            timedOutQueryId === null &&
            areFiltersValid &&
            isValidFunnel &&
            funnelsFilter?.funnel_viz_type === FunnelVizType.Steps &&
            !disableTable
        ) {
            return (
                <>
                    {/* <h2 className="my-4 mx-0">Detailed results</h2> */}
                    {/* <FunnelStepsTable /> */}
                </>
            )
        }

        // InsightsTable is loaded for all trend views (except below), plus the sessions view.
        // Exclusions:
        // 1. Table view. Because table is already loaded anyways in `Trends.tsx` as the main component.
        // 2. Bar value chart. Because this view displays data in completely different dimensions.
        if (
            isTrends &&
            (!display || (display !== ChartDisplayType.ActionsTable && display !== ChartDisplayType.ActionsBarValue)) &&
            !disableTable
        ) {
            return (
                <>
                    {exportContext && (
                        <div className="flex items-center justify-between my-4 mx-0">
                            <h2 className="m-0">Detailed results</h2>
                            <Tooltip title="Export this table in CSV format" placement="left">
                                <ExportButton
                                    type="secondary"
                                    status="primary"
                                    items={[
                                        {
                                            export_format: ExporterFormat.CSV,
                                            export_context: exportContext,
                                        },
                                    ]}
                                />
                            </Tooltip>
                        </div>
                    )}

                    <InsightsTableDataExploration
                        isLegend
                        filterKey="trends_TRENDS"
                        canEditSeriesNameInline={!trendsFilter?.formula && insightMode === ItemMode.Edit}
                        canCheckUncheckSeries={canEditInsight}
                    />
                </>
            )
        }

        return null
    }

    return (
        <>
            {/* {isUsingSessionAnalysis ? (
                <div className="mb-4">
                    <AlertMessage type="info">
                        When using sessions and session properties, events without session IDs will be excluded from the
                        set of results.{' '}
                        <a href="https://posthog.com/docs/user-guides/sessions">Learn more about sessions.</a>
                    </AlertMessage>
                </div>
            ) : null} */}
            {/* These are filters that are reused between insight features. They each have generic logic that updates the url */}
            <Card
                title={disableHeader ? null : <InsightDisplayConfig disableTable={!!disableTable} />}
                data-attr="insights-graph"
                className="insights-graph-container"
            >
                <div>
                    <div
                        className={clsx('flex items-center justify-between insights-graph-header', {
                            funnels: isFunnels,
                        })}
                    >
                        {/*Don't add more than two columns in this row.*/}
                        {!disableLastComputation && (
                            <div>
                                <ComputationTimeWithRefresh />
                            </div>
                        )}
                        <div>
                            {isFunnels ? <FunnelCanvasLabel /> : null}
                            {isPaths ? <PathCanvasLabel /> : null}
                            <InsightLegendButton />
                        </div>
                    </div>
                    {!!BlockingEmptyState ? (
                        BlockingEmptyState
                    ) : supportsDisplay && (insightFilter as TrendsFilter | StickinessFilter)?.show_legend ? (
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
            {renderTable()}
            {/* {!disableCorrelationTable && correlationAnalysisAvailable && activeView === InsightType.FUNNELS && (
                <FunnelCorrelation />
            )} */}
        </>
    )
}
