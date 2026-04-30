import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { FunnelCanvasLabel } from 'scenes/funnels/FunnelCanvasLabel'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import {
    BoxPlotMissingPropertyState,
    FunnelDataWarehouseStepIncompleteState,
    FunnelSingleStepState,
    InsightEmptyState,
    InsightErrorState,
    InsightLoadingState,
    InsightRefreshDataHint,
    InsightTimeoutState,
    InsightValidationError,
} from 'scenes/insights/EmptyStates'
import { InsightAIAnalysis } from 'scenes/insights/InsightAIAnalysis'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { isBoxPlotMissingProperty } from 'scenes/insights/utils/queryUtils'
import { BoxPlotLegend } from 'scenes/insights/views/BoxPlot/BoxPlotLegend'
import { BoxPlotResultsTable } from 'scenes/insights/views/BoxPlot/BoxPlotResultsTable'
import { FunnelCorrelation } from 'scenes/insights/views/Funnels/FunnelCorrelation'
import { FunnelStepsTable } from 'scenes/insights/views/Funnels/FunnelStepsTable'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { PathsV2 } from 'scenes/paths-v2/PathsV2'
import { Paths } from 'scenes/paths/Paths'
import { PathCanvasLabel } from 'scenes/paths/PathsLabel'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { TrendInsight } from 'scenes/trends/Trends'
import { WebAnalyticsInsight } from 'scenes/web-analytics/WebAnalyticsInsight'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { shouldQueryBeAsync } from '~/queries/utils'
import { ChartDisplayType, ExporterFormat, FunnelVizType, InsightLogicProps, InsightType } from '~/types'

import { InsightDisplayConfig } from './InsightDisplayConfig'
import { InsightResultMetadata } from './InsightResultMetadata'
import { ResultCustomizationsModal } from './ResultCustomizationsModal'

/** When the dashboard is still streaming/refreshing tiles, prefer loading UX over "Chart data didn't load". */
function DashboardInsightRefreshHintOrLoading({
    dashboardId,
    dashboardItemId,
    insightProps,
    queryId,
    context,
    onRetry,
}: {
    dashboardId: number
    dashboardItemId: InsightLogicProps['dashboardItemId']
    insightProps: InsightLogicProps
    queryId: string | null
    context?: QueryContext<InsightVizNode>
    onRetry: () => void
}): JSX.Element {
    const { itemsLoading, isRefreshingQueued, isRefreshing } = useValues(dashboardLogic({ id: dashboardId }))
    const shortId =
        dashboardItemId && typeof dashboardItemId === 'string' && !dashboardItemId.startsWith('new')
            ? dashboardItemId
            : null
    const tilePending = shortId !== null && (isRefreshingQueued(shortId) || isRefreshing(shortId))
    if (itemsLoading || tilePending) {
        return (
            <InsightLoadingState
                queryId={queryId}
                key={queryId}
                insightProps={insightProps}
                renderEmptyStateAsSkeleton={context?.renderEmptyStateAsSkeleton}
            />
        )
    }
    return <InsightRefreshDataHint onRetry={onRetry} />
}

/** Dashboard tile: show refresh when merged `result` is still nullish (empty success is `[]`, not `null`). */
export function shouldShowDashboardInsightRefreshHint({
    isInDashboardContext,
    doNotLoad,
    activeView,
    insightData,
}: {
    isInDashboardContext: boolean
    doNotLoad?: boolean
    activeView: InsightType
    insightData: Record<string, any> | null | undefined
}): boolean {
    if (!isInDashboardContext || doNotLoad || activeView === InsightType.WEB_ANALYTICS) {
        return false
    }
    const rawResult = insightData?.result
    return rawResult === null || rawResult === undefined
}

export function InsightVizDisplay({
    disableHeader,
    disableTable,
    disableCorrelationTable,
    disableLastComputation,
    disableLastComputationRefresh,
    showingResults,
    context,
    embedded,
    inSharedMode,
    editMode,
}: {
    disableHeader?: boolean
    disableTable?: boolean
    disableCorrelationTable?: boolean
    disableLastComputation?: boolean
    disableLastComputationRefresh?: boolean
    showingResults?: boolean
    context?: QueryContext<InsightVizNode>
    embedded: boolean
    inSharedMode?: boolean
    editMode?: boolean
}): JSX.Element | null {
    const { insightProps, canEditInsight, isUsingPathsV1, isUsingPathsV2, isInDashboardContext } =
        useValues(insightLogic)

    const { activeView } = useValues(insightNavLogic(insightProps))

    const {
        isFunnels,
        isPaths,
        hasDetailedResultsTable,
        showLegend,
        hasFormula,
        supportsDisplay,
        samplingFactor,
        insightDataLoading,
        erroredQueryId,
        timedOutQueryId,
        vizSpecificOptions,
        query,
        querySource,
        display,
        series,
        insightData,
        validationError,
        theme,
    } = useValues(insightVizDataLogic(insightProps))
    const { loadData } = useActions(insightVizDataLogic(insightProps))
    const { exportContext, queryId } = useValues(insightDataLogic(insightProps))
    const { funnelsFilter, hasFunnelResults, isFunnelWithEnoughSteps, isFunnelWithIncompleteDataWarehouseStep } =
        useValues(funnelDataLogic(insightProps))

    const isFlowViz = funnelsFilter?.funnelVizType === FunnelVizType.Flow
    const actionable = !embedded && editMode

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        if (insightDataLoading) {
            return (
                <InsightLoadingState
                    queryId={queryId}
                    key={queryId}
                    insightProps={insightProps}
                    renderEmptyStateAsSkeleton={context?.renderEmptyStateAsSkeleton}
                />
            )
        }

        // Insight specific empty states - note order is important here
        if (
            display === ChartDisplayType.BoxPlot &&
            isBoxPlotMissingProperty(series as TrendsQuery['series'] | null | undefined)
        ) {
            return <BoxPlotMissingPropertyState />
        }

        if (activeView === InsightType.FUNNELS && !isFlowViz) {
            if (isFunnelWithIncompleteDataWarehouseStep) {
                return <FunnelDataWarehouseStepIncompleteState />
            }

            if (!isFunnelWithEnoughSteps) {
                return <FunnelSingleStepState actionable={actionable} />
            }
        }

        if (validationError) {
            return (
                <InsightValidationError
                    query={query}
                    detail={validationError}
                    onRetry={() => {
                        loadData(query && shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')
                    }}
                />
            )
        }

        // Insight agnostic empty states
        if (erroredQueryId) {
            return (
                <InsightErrorState
                    query={query}
                    queryId={erroredQueryId}
                    onRetry={() => {
                        loadData(query && shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')
                    }}
                />
            )
        }
        if (timedOutQueryId) {
            return <InsightTimeoutState queryId={timedOutQueryId} />
        }

        // On a dashboard, users sometimes see an empty chart even though the insight is valid—often because
        // they navigated away while numbers were still loading, or nothing was cached yet. Prompt them to
        // refresh rather than staring at a blank tile. this is possible if the redis cache is a miss, and they dont have anything
        // cached on their browser yet either.
        if (
            shouldShowDashboardInsightRefreshHint({
                isInDashboardContext,
                doNotLoad: insightProps.doNotLoad,
                activeView,
                insightData,
            })
        ) {
            const onRetry = (): void => loadData(query && shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')
            if (insightProps.dashboardId != null) {
                return (
                    <DashboardInsightRefreshHintOrLoading
                        dashboardId={insightProps.dashboardId}
                        dashboardItemId={insightProps.dashboardItemId}
                        insightProps={insightProps}
                        queryId={queryId}
                        context={context}
                        onRetry={onRetry}
                    />
                )
            }
            return <InsightRefreshDataHint onRetry={onRetry} />
        }

        if (activeView === InsightType.FUNNELS && !isFlowViz) {
            if (!hasFunnelResults && !erroredQueryId && !insightDataLoading) {
                return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
            }
        }

        return null
    })()

    function renderActiveView(): JSX.Element | null {
        switch (activeView) {
            case InsightType.TRENDS:
                return (
                    <TrendInsight
                        view={InsightType.TRENDS}
                        editMode={editMode}
                        context={context}
                        embedded={embedded}
                        inSharedMode={inSharedMode}
                    />
                )
            case InsightType.STICKINESS:
                return (
                    <TrendInsight
                        view={InsightType.STICKINESS}
                        editMode={editMode}
                        context={context}
                        embedded={embedded}
                        inSharedMode={inSharedMode}
                    />
                )
            case InsightType.LIFECYCLE:
                return (
                    <TrendInsight
                        view={InsightType.LIFECYCLE}
                        editMode={editMode}
                        context={context}
                        embedded={embedded}
                        inSharedMode={inSharedMode}
                    />
                )
            case InsightType.FUNNELS:
                return <Funnel inCardView={embedded} inSharedMode={inSharedMode} showPersonsModal={!inSharedMode} />
            case InsightType.RETENTION:
                return (
                    <RetentionContainer
                        context={context}
                        vizSpecificOptions={vizSpecificOptions?.[InsightType.RETENTION]}
                        inCardView={embedded}
                        embedded={embedded}
                        inSharedMode={inSharedMode}
                    />
                )
            case InsightType.PATHS:
                return isUsingPathsV2 ? <PathsV2 /> : <Paths />
            case InsightType.WEB_ANALYTICS:
                return <WebAnalyticsInsight context={context} editMode={editMode} />
            default:
                return null
        }
    }

    function renderTable(): JSX.Element | null {
        if (
            isFunnels &&
            erroredQueryId === null &&
            timedOutQueryId === null &&
            isFunnelWithEnoughSteps &&
            hasFunnelResults &&
            (funnelsFilter?.funnelVizType === FunnelVizType.Steps ||
                funnelsFilter?.funnelVizType === FunnelVizType.Flow) &&
            !disableTable
        ) {
            return (
                <SceneSection
                    title={<span className="font-semibold text-lg m-0">Detailed results</span>}
                    className="mt-4"
                >
                    <FunnelStepsTable />
                </SceneSection>
            )
        }

        if (display === ChartDisplayType.BoxPlot && !disableTable) {
            return (
                <div className="mt-4">
                    <h2 className="font-semibold text-lg m-0 mb-2">Detailed results</h2>
                    <BoxPlotResultsTable />
                </div>
            )
        }

        if (hasDetailedResultsTable && !disableTable) {
            return (
                <>
                    {exportContext && (
                        <div className="flex items-center justify-between my-4 mx-0">
                            <h2 className="font-semibold text-lg m-0">Detailed results</h2>
                            <Tooltip title="Export this table" placement="left">
                                <ExportButton
                                    type="secondary"
                                    items={[
                                        {
                                            export_format: ExporterFormat.CSV,
                                            export_context: exportContext,
                                        },
                                        {
                                            export_format: ExporterFormat.XLSX,
                                            export_context: exportContext,
                                        },
                                    ]}
                                />
                            </Tooltip>
                        </div>
                    )}

                    <InsightsTable
                        // Do not show ribbons for world map insight table. All ribbons are nuances of blue, and do not bring any UX value
                        isLegend={display !== ChartDisplayType.WorldMap}
                        embedded={embedded}
                        editMode={editMode}
                        filterKey={keyForInsightLogicProps('new')(insightProps)}
                        canEditSeriesNameInline={!hasFormula && editMode}
                        seriesNameTooltip={hasFormula && editMode ? 'Formula series names are not editable' : undefined}
                        canCheckUncheckSeries={canEditInsight}
                    />
                </>
            )
        }

        return null
    }

    function renderAIAnalysisSection(): JSX.Element | null {
        // Only show in view mode
        if (editMode) {
            return null
        }

        // Don't show in embedded or shared mode
        if (embedded || inSharedMode) {
            return null
        }

        // Only show for insight query nodes (use querySource which is the actual InsightQueryNode)
        if (!querySource) {
            return null
        }

        return <InsightAIAnalysis query={querySource} />
    }

    const showComputationMetadata = !disableLastComputation || !!samplingFactor

    // Web Analytics insights don't use themes, so allow them to render without waiting for theme to load
    if (!theme && activeView !== InsightType.WEB_ANALYTICS) {
        return null
    }

    return (
        <>
            {/* These are filters that are reused between insight features. They each have generic logic that updates the url */}
            <div
                className={clsx(
                    `InsightVizDisplay InsightVizDisplay--type-${activeView.toLowerCase()}`,
                    !embedded && 'border rounded bg-surface-primary'
                )}
                data-attr="insights-graph"
            >
                {disableHeader ? null : <InsightDisplayConfig />}
                {showingResults && (
                    <>
                        {!embedded &&
                            ((isFunnels && hasFunnelResults) ||
                                isPaths ||
                                (showComputationMetadata && !BlockingEmptyState)) && (
                                <div className="flex items-center justify-between gap-2 p-2 flex-wrap-reverse border-b">
                                    <div className="flex items-center gap-2">
                                        {showComputationMetadata && (
                                            <InsightResultMetadata
                                                disableLastComputation={disableLastComputation}
                                                disableLastComputationRefresh={disableLastComputationRefresh}
                                            />
                                        )}
                                    </div>

                                    <div className="flex items-center gap-2">
                                        {isPaths && isUsingPathsV1 && <PathCanvasLabel />}
                                        {isFunnels && <FunnelCanvasLabel />}
                                    </div>
                                </div>
                            )}

                        <div
                            className={clsx(
                                'InsightVizDisplay__content',
                                supportsDisplay && showLegend && 'InsightVizDisplay__content--with-legend'
                            )}
                        >
                            {BlockingEmptyState ? (
                                BlockingEmptyState
                            ) : supportsDisplay && showLegend ? (
                                <>
                                    <div className="InsightVizDisplay__content__left">{renderActiveView()}</div>
                                    <div className="InsightVizDisplay__content__right empty:hidden">
                                        {display === ChartDisplayType.BoxPlot ? <BoxPlotLegend /> : <InsightLegend />}
                                    </div>
                                </>
                            ) : (
                                <>{renderActiveView()}</>
                            )}
                        </div>
                    </>
                )}
            </div>
            <ResultCustomizationsModal />
            {renderAIAnalysisSection()}
            {renderTable()}
            {!disableCorrelationTable && activeView === InsightType.FUNNELS && <FunnelCorrelation />}
        </>
    )
}
