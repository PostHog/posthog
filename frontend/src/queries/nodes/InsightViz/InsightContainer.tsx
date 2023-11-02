import { Card, Col, Row } from 'antd'
import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'

import { QueryContext } from '~/queries/types'
import { ChartDisplayType, ExporterFormat, FunnelVizType, InsightType, ItemMode } from '~/types'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { Animation } from 'lib/components/Animation/Animation'
import { AnimationType } from 'lib/animations/animations'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'

import { InsightDisplayConfig } from './InsightDisplayConfig'
import { FunnelCanvasLabel } from 'scenes/funnels/FunnelCanvasLabel'
import { TrendInsight } from 'scenes/trends/Trends'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { Paths } from 'scenes/paths/Paths'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'
import {
    FunnelInvalidExclusionState,
    FunnelSingleStepState,
    InsightEmptyState,
    InsightErrorState,
    InsightTimeoutState,
} from 'scenes/insights/EmptyStates'
import { PathCanvasLabel } from 'scenes/paths/PathsLabel'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { FunnelInsight } from 'scenes/insights/views/Funnels/FunnelInsight'
import { FunnelStepsTable } from 'scenes/insights/views/Funnels/FunnelStepsTable'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { FunnelCorrelation } from 'scenes/insights/views/Funnels/FunnelCorrelation'
import { InsightResultMetadata } from './InsightResultMetadata'
import { Link } from '@posthog/lemon-ui'

const VIEW_MAP = {
    [`${InsightType.TRENDS}`]: <TrendInsight view={InsightType.TRENDS} />,
    [`${InsightType.STICKINESS}`]: <TrendInsight view={InsightType.STICKINESS} />,
    [`${InsightType.LIFECYCLE}`]: <TrendInsight view={InsightType.LIFECYCLE} />,
    [`${InsightType.FUNNELS}`]: <FunnelInsight />,
    [`${InsightType.RETENTION}`]: <RetentionContainer />,
    [`${InsightType.PATHS}`]: <Paths />,
}

export function InsightContainer({
    disableHeader,
    disableTable,
    disableCorrelationTable,
    disableLastComputation,
    disableLastComputationRefresh,
    showingResults,
    insightMode,
    context,
    embedded,
}: {
    disableHeader?: boolean
    disableTable?: boolean
    disableCorrelationTable?: boolean
    disableLastComputation?: boolean
    disableLastComputationRefresh?: boolean
    showingResults?: boolean
    insightMode?: ItemMode
    context?: QueryContext
    embedded: boolean
}): JSX.Element {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { activeView } = useValues(insightNavLogic(insightProps))

    const { isFunnelWithEnoughSteps, hasFunnelResults, areExclusionFiltersValid } = useValues(
        funnelDataLogic(insightProps)
    )
    const {
        isTrends,
        isFunnels,
        isPaths,
        display,
        showLegend,
        trendsFilter,
        funnelsFilter,
        supportsDisplay,
        isUsingSessionAnalysis,
        samplingFactor,
        insightDataLoading,
        erroredQueryId,
        timedOutQueryId,
    } = useValues(insightVizDataLogic(insightProps))
    const { exportContext } = useValues(insightDataLogic(insightProps))

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        if (insightDataLoading) {
            return (
                <>
                    <div className="text-center">
                        <Animation type={AnimationType.LaptopHog} />
                    </div>
                    {!!timedOutQueryId && (
                        <InsightTimeoutState isLoading={true} queryId={timedOutQueryId} insightProps={insightProps} />
                    )}
                </>
            )
        }

        // Insight specific empty states - note order is important here
        if (activeView === InsightType.FUNNELS) {
            if (!isFunnelWithEnoughSteps) {
                return <FunnelSingleStepState actionable={insightMode === ItemMode.Edit || disableTable} />
            }
            if (!areExclusionFiltersValid) {
                return <FunnelInvalidExclusionState />
            }
            if (!hasFunnelResults && !erroredQueryId && !insightDataLoading) {
                return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
            }
        }

        // Insight agnostic empty states
        if (erroredQueryId) {
            return <InsightErrorState queryId={erroredQueryId} />
        }
        if (timedOutQueryId) {
            return (
                <InsightTimeoutState
                    isLoading={insightDataLoading}
                    queryId={timedOutQueryId}
                    insightProps={insightProps}
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
            isFunnelWithEnoughSteps &&
            hasFunnelResults &&
            funnelsFilter?.funnel_viz_type === FunnelVizType.Steps &&
            !disableTable
        ) {
            return (
                <>
                    <h2 className="font-semibold text-lg my-4 mx-0">Detailed results</h2>
                    <FunnelStepsTable />
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
                            <h2 className="font-semibold text-lg m-0">Detailed results</h2>
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

                    <InsightsTable
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
            {isUsingSessionAnalysis ? (
                <div className="mb-4">
                    <LemonBanner type="info">
                        When using sessions and session properties, events without session IDs will be excluded from the
                        set of results.{' '}
                        <Link to="https://posthog.com/docs/user-guides/sessions">Learn more about sessions.</Link>
                    </LemonBanner>
                </div>
            ) : null}
            {/* These are filters that are reused between insight features. They each have generic logic that updates the url */}
            <Card
                title={disableHeader ? null : <InsightDisplayConfig />}
                data-attr="insights-graph"
                className="insights-graph-container"
                bordered={!embedded}
            >
                {showingResults && (
                    <div>
                        {isFunnels && (
                            <div className="overflow-hidden">
                                {/* negative margin-top so that the border is only visible when the rows wrap */}
                                <div className="flex flex-wrap-reverse whitespace-nowrap gap-x-8 -mt-px">
                                    {(!disableLastComputation || !!samplingFactor) && (
                                        <div className="flex grow items-center insights-graph-header border-t">
                                            <InsightResultMetadata
                                                disableLastComputation={disableLastComputation}
                                                disableLastComputationRefresh={disableLastComputationRefresh}
                                            />
                                        </div>
                                    )}
                                    <div
                                        className={`flex insights-graph-header ${
                                            disableLastComputation ? 'border-b w-full mb-4' : 'border-t'
                                        }`}
                                    >
                                        <FunnelCanvasLabel />
                                    </div>
                                </div>
                            </div>
                        )}

                        {!isFunnels && (!disableLastComputation || !!samplingFactor) && (
                            <div className="flex items-center justify-between insights-graph-header">
                                <div className="flex items-center">
                                    <InsightResultMetadata
                                        disableLastComputation={disableLastComputation}
                                        disableLastComputationRefresh={disableLastComputationRefresh}
                                    />
                                </div>

                                <div>{isPaths ? <PathCanvasLabel /> : null}</div>
                            </div>
                        )}

                        {BlockingEmptyState ? (
                            BlockingEmptyState
                        ) : supportsDisplay && showLegend ? (
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
                )}
            </Card>
            {renderTable()}
            {!disableCorrelationTable && activeView === InsightType.FUNNELS && <FunnelCorrelation />}
        </>
    )
}
