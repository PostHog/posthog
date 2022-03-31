import { Card, Col, Progress, Row } from 'antd'
import { InsightDisplayConfig } from 'scenes/insights/InsightTabs/InsightDisplayConfig'
import { FunnelCanvasLabel } from 'scenes/funnels/FunnelCanvasLabel'
import { ComputationTimeWithRefresh } from 'scenes/insights/ComputationTimeWithRefresh'
import { FunnelVizType, InsightType, ItemMode } from '~/types'
import { TrendInsight } from 'scenes/trends/Trends'
import { FunnelInsight } from 'scenes/insights/FunnelInsight'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { Paths } from 'scenes/paths/Paths'
import { ACTIONS_BAR_CHART_VALUE, ACTIONS_TABLE, FEATURE_FLAGS, FunnelLayout } from 'lib/constants'
import { FunnelStepTable } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepTable'
import { BindLogic, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightsTable } from 'scenes/insights/InsightsTable'
import React, { useEffect, useRef, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import {
    FunnelInvalidExclusionState,
    FunnelSingleStepState,
    InsightEmptyState,
    InsightErrorState,
    InsightTimeoutState,
} from 'scenes/insights/EmptyStates'
import { Loading } from 'lib/utils'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import clsx from 'clsx'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PathCanvasLabel } from 'scenes/paths/PathsLabel'
import { FunnelCorrelation } from './FunnelCorrelation'
import { InsightLegend, InsightLegendButton } from 'lib/components/InsightLegend/InsightLegend'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { UserSQLInsight } from 'scenes/userSQL/UserSQL'
import { LemonButton } from 'lib/components/LemonButton'

const VIEW_MAP = {
    [`${InsightType.TRENDS}`]: <TrendInsight view={InsightType.TRENDS} />,
    [`${InsightType.STICKINESS}`]: <TrendInsight view={InsightType.STICKINESS} />,
    [`${InsightType.LIFECYCLE}`]: <TrendInsight view={InsightType.LIFECYCLE} />,
    [`${InsightType.FUNNELS}`]: <FunnelInsight />,
    [`${InsightType.RETENTION}`]: <RetentionContainer />,
    [`${InsightType.PATHS}`]: <Paths />,
    [`${InsightType.USER_SQL}`]: <UserSQLInsight />,
}

export function InsightContainer(
    { disableHeader, disableTable }: { disableHeader?: boolean; disableTable?: boolean } = {
        disableHeader: false,
        disableTable: false,
    }
): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { insightMode } = useValues(insightSceneLogic)
    const {
        insightProps,
        canEditInsight,
        insightLoading,
        activeView,
        loadedView,
        filters,
        showTimeoutMessage,
        showErrorMessage,
        percentResultsLoaded,
        insight,
    } = useValues(insightLogic)
    const { areFiltersValid, isValidFunnel, areExclusionFiltersValid, correlationAnalysisAvailable } = useValues(
        funnelLogic(insightProps)
    )

    const [delayedPercentComplete, setDelayedPercentComplete] = useState(0)
    const [showProgress, setShowProgress] = useState(false)
    const showVideoTimeout = useRef(null)

    const [showVideo, setShowVideo] = useState(false)
    const [showResultsReady, setShowResultsReady] = useState(false)

    useEffect(() => {
        if (insight.status && insight.status?.complete) {
            setDelayedPercentComplete(100)
            setTimeout(() => {
                setShowProgress(false)
                setDelayedPercentComplete(0)
            }, 500)
        } else {
            setShowProgress(true)
            setDelayedPercentComplete(percentResultsLoaded)
        }
    }, [percentResultsLoaded, insight.status?.complete])

    useEffect(() => {
        console.log(percentResultsLoaded)
        if (
            filters.insight === InsightType.USER_SQL &&
            showProgress &&
            !showVideoTimeout.current &&
            percentResultsLoaded
        ) {
            console.log('setting timeout')
            showVideoTimeout.current = setTimeout(() => {
                console.log('show video')
                setShowVideo(true)
            }, 3000)
        }
        if (!showProgress && showVideoTimeout.current) {
            console.log('clearing timeout')
            clearTimeout(showVideoTimeout.current)
            showVideoTimeout.current = null
            if (showVideo) {
                setShowResultsReady(true)
            } else {
                setShowVideo(false)
            }
        }
    }, [showProgress, percentResultsLoaded])

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        if (
            activeView !== loadedView ||
            ((insightLoading || (filters.insight === InsightType.USER_SQL && (showProgress || showVideo))) &&
                !showTimeoutMessage)
        ) {
            return (
                <>
                    {filters.insight === InsightType.USER_SQL ? (
                        <>
                            <Progress percent={delayedPercentComplete ?? 0} showInfo={false} />
                            {showVideo && (
                                <div style={{ textAlign: 'center', padding: 15 }}>
                                    <h1 style={{ textAlign: 'center', paddingBottom: 15 }}>
                                        You're stretching our database. Why not stretch your back while we're at it?
                                    </h1>
                                    <iframe
                                        width="560"
                                        height="315"
                                        src="https://www.youtube.com/embed/Ezo-IsqfEVo?autoplay=1"
                                        title="YouTube video player"
                                        frameBorder="0"
                                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                                        allowFullScreen
                                     />
                                    {showResultsReady && (
                                        <div
                                            style={{
                                                width: '100%',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                            }}
                                        >
                                            <LemonButton
                                                type="primary"
                                                style={{ marginTop: 15, alignSelf: 'center' }}
                                                onClick={() => {
                                                    setShowResultsReady(false)
                                                    setShowVideo(false)
                                                }}
                                            >
                                                Results are ready
                                            </LemonButton>
                                        </div>
                                    )}
                                </div>
                            )}
                        </>
                    ) : (
                        <Loading />
                    )}
                    {
                        filters.display !== ACTIONS_TABLE && (
                            <div className="trends-insights-container" />
                        ) /* Tables don't need this padding, but graphs do for sizing */
                    }
                </>
            )
        }
        // Insight specific empty states - note order is important here
        if (loadedView === InsightType.FUNNELS) {
            if (!areFiltersValid) {
                return <FunnelSingleStepState actionable={insightMode === ItemMode.Edit || disableTable} />
            }
            if (!areExclusionFiltersValid) {
                return <FunnelInvalidExclusionState />
            }
            if (!isValidFunnel && !insightLoading && insight.status?.complete) {
                return <InsightEmptyState />
            }
        }

        // Insight agnostic empty states
        if (showErrorMessage) {
            return <InsightErrorState />
        }
        if (showTimeoutMessage) {
            return <InsightTimeoutState isLoading={insightLoading} />
        }

        return null
    })()

    function renderTable(): JSX.Element | null {
        if (
            activeView === InsightType.FUNNELS &&
            !showErrorMessage &&
            !showTimeoutMessage &&
            areFiltersValid &&
            filters.funnel_viz_type === FunnelVizType.Steps &&
            filters?.layout === FunnelLayout.horizontal &&
            !disableTable
        ) {
            return <FunnelStepTable />
        }
        if (
            (!filters.display ||
                (filters?.display !== ACTIONS_TABLE && filters?.display !== ACTIONS_BAR_CHART_VALUE)) &&
            activeView === InsightType.TRENDS &&
            !disableTable
        ) {
            /* InsightsTable is loaded for all trend views (except below), plus the sessions view.
    Exclusions:
        1. Table view. Because table is already loaded anyways in `Trends.tsx` as the main component.
        2. Bar value chart. Because this view displays data in completely different dimensions.
    */
            return (
                <BindLogic logic={trendsLogic} props={insightProps}>
                    <InsightsTable
                        isLegend
                        showTotalCount
                        filterKey={activeView === InsightType.TRENDS ? `trends_${activeView}` : ''}
                        canEditSeriesNameInline={activeView === InsightType.TRENDS && insightMode === ItemMode.Edit}
                        canCheckUncheckSeries={!canEditInsight}
                    />
                </BindLogic>
            )
        }

        return null
    }
    return activeView === InsightType.USER_SQL && insight.result?.length === 0 ? (
        <></>
    ) : (
        <>
            {/* These are filters that are reused between insight features. They each have generic logic that updates the url */}
            <Card
                title={
                    disableHeader ? null : (
                        <InsightDisplayConfig
                            activeView={activeView as InsightType}
                            insightMode={insightMode}
                            filters={filters}
                            disableTable={!!disableTable}
                            disabled={!canEditInsight}
                        />
                    )
                }
                data-attr="insights-graph"
                className="insights-graph-container"
            >
                <div>
                    {activeView !== InsightType.USER_SQL && (
                        <Row
                            className={clsx('insights-graph-header', {
                                funnels: activeView === InsightType.FUNNELS,
                            })}
                            align="middle"
                            justify="space-between"
                        >
                            {/*Don't add more than two columns in this row.*/}
                            <Col>
                                <ComputationTimeWithRefresh />
                            </Col>
                            <Col>
                                {activeView === InsightType.FUNNELS ? <FunnelCanvasLabel /> : null}
                                {activeView === InsightType.PATHS ? <PathCanvasLabel /> : null}
                                <InsightLegendButton />
                            </Col>
                        </Row>
                    )}
                    {!!BlockingEmptyState ? (
                        BlockingEmptyState
                    ) : featureFlags[FEATURE_FLAGS.INSIGHT_LEGENDS] &&
                      (activeView === InsightType.TRENDS || activeView === InsightType.STICKINESS) &&
                      filters.show_legend ? (
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
            {!disableTable && correlationAnalysisAvailable && activeView === InsightType.FUNNELS && (
                <FunnelCorrelation />
            )}
        </>
    )
}
