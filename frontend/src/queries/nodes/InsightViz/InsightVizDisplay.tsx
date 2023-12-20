import clsx from 'clsx'
import { useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { Funnel } from 'scenes/funnels/Funnel'
import { FunnelCanvasLabel } from 'scenes/funnels/FunnelCanvasLabel'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import {
    FunnelInvalidExclusionState,
    FunnelSingleStepState,
    InsightEmptyState,
    InsightErrorState,
    InsightTimeoutState,
} from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { FunnelCorrelation } from 'scenes/insights/views/Funnels/FunnelCorrelation'
import { FunnelStepsTable } from 'scenes/insights/views/Funnels/FunnelStepsTable'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { Paths } from 'scenes/paths/Paths'
import { PathCanvasLabel } from 'scenes/paths/PathsLabel'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { TrendInsight } from 'scenes/trends/Trends'

import { QueryContext } from '~/queries/types'
import { ChartDisplayType, ExporterFormat, FunnelVizType, InsightType, ItemMode } from '~/types'

import { InsightDisplayConfig } from './InsightDisplayConfig'
import { InsightResultMetadata } from './InsightResultMetadata'

export function InsightVizDisplay({
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

    const { hasFunnelResults } = useValues(funnelDataLogic(insightProps))
    const { isFunnelWithEnoughSteps, areExclusionFiltersValid } = useValues(insightVizDataLogic(insightProps))
    const {
        isTrends,
        isFunnels,
        isPaths,
        display,
        showLegend,
        trendsFilter,
        funnelsFilter,
        supportsDisplay,
        samplingFactor,
        insightDataLoading,
        erroredQueryId,
        timedOutQueryId,
        vizSpecificOptions,
    } = useValues(insightVizDataLogic(insightProps))
    const { exportContext } = useValues(insightDataLogic(insightProps))

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        if (insightDataLoading) {
            return (
                <div className="flex flex-col flex-1 justify-center items-center">
                    <Animation type={AnimationType.LaptopHog} />
                    {!!timedOutQueryId && (
                        <InsightTimeoutState isLoading={true} queryId={timedOutQueryId} insightProps={insightProps} />
                    )}
                </div>
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

    function renderActiveView(): JSX.Element | null {
        switch (activeView) {
            case InsightType.TRENDS:
                return <TrendInsight view={InsightType.TRENDS} context={context} />
            case InsightType.STICKINESS:
                return <TrendInsight view={InsightType.STICKINESS} context={context} />
            case InsightType.LIFECYCLE:
                return <TrendInsight view={InsightType.LIFECYCLE} context={context} />
            case InsightType.FUNNELS:
                return <Funnel />
            case InsightType.RETENTION:
                return (
                    <RetentionContainer
                        context={context}
                        vizSpecificOptions={vizSpecificOptions?.[InsightType.RETENTION]}
                    />
                )
            case InsightType.PATHS:
                return <Paths />
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

    const showComputationMetadata = !disableLastComputation || !!samplingFactor

    return (
        <>
            {/* These are filters that are reused between insight features. They each have generic logic that updates the url */}
            <div
                className={clsx(
                    `InsightVizDisplay InsightVizDisplay--type-${activeView.toLowerCase()} ph-no-capture`,
                    !embedded && 'border rounded bg-bg-light'
                )}
                data-attr="insights-graph"
            >
                {disableHeader ? null : <InsightDisplayConfig />}
                {showingResults && (
                    <>
                        {(isFunnels || isPaths || showComputationMetadata) && (
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
                                    {isPaths && <PathCanvasLabel />}
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
                                    <div className="InsightVizDisplay__content__right">
                                        <InsightLegend />
                                    </div>
                                </>
                            ) : (
                                renderActiveView()
                            )}
                        </div>
                    </>
                )}
            </div>
            {renderTable()}
            {!disableCorrelationTable && activeView === InsightType.FUNNELS && <FunnelCorrelation />}
        </>
    )
}
