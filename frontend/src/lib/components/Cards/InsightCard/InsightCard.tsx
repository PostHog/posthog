import './InsightCard.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import React, { useState } from 'react'
import { Layout } from 'react-grid-layout'
import { Funnel } from 'scenes/funnels/Funnel'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import {
    FunnelSingleStepState,
    InsightEmptyState,
    InsightErrorState,
    InsightTimeoutState,
    InsightValidationError,
} from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { isFilterWithDisplay, isFunnelsFilter, isPathsFilter, isRetentionFilter } from 'scenes/insights/sharedUtils'
import { BoldNumber } from 'scenes/insights/views/BoldNumber'
import { DashboardInsightsTable } from 'scenes/insights/views/InsightsTable/DashboardInsightsTable'
import { WorldMap } from 'scenes/insights/views/WorldMap'
import { Paths } from 'scenes/paths/Paths'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { ActionsHorizontalBar, ActionsLineGraph, ActionsPie } from 'scenes/trends/viz'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { insightVizDataCollectionId, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults, getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { Query } from '~/queries/Query/Query'
import { InsightQueryNode } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import {
    ChartDisplayType,
    ChartParams,
    DashboardBasicType,
    DashboardPlacement,
    DashboardTile,
    DashboardType,
    FilterType,
    InsightColor,
    InsightLogicProps,
    InsightModel,
    InsightType,
} from '~/types'

import { ResizeHandle1D, ResizeHandle2D } from '../handles'
import { InsightMeta } from './InsightMeta'

type DisplayedType = ChartDisplayType | 'RetentionContainer' | 'FunnelContainer' | 'PathsContainer'

const displayMap: Record<
    DisplayedType,
    {
        className: string
        element: (props: ChartParams) => JSX.Element | null
    }
> = {
    ActionsLineGraph: {
        className: 'graph',
        element: ActionsLineGraph,
    },
    ActionsLineGraphCumulative: {
        className: 'graph',
        element: ActionsLineGraph,
    },
    ActionsAreaGraph: {
        className: 'graph',
        element: ActionsLineGraph,
    },
    ActionsBar: {
        className: 'bar',
        element: ActionsLineGraph,
    },
    ActionsBarValue: {
        className: 'bar',
        element: ActionsHorizontalBar,
    },
    ActionsStackedBar: {
        className: 'bar',
        element: ActionsLineGraph,
    },
    ActionsTable: {
        className: 'table',
        element: DashboardInsightsTable,
    },
    ActionsPie: {
        className: 'pie',
        element: ActionsPie,
    },
    FunnelContainer: {
        className: 'funnel',
        element: Funnel,
    },
    RetentionContainer: {
        className: 'retention',
        element: RetentionContainer,
    },
    PathsContainer: {
        className: 'paths-viz',
        element: Paths,
    },
    WorldMap: {
        className: 'world-map',
        element: WorldMap,
    },
    BoldNumber: {
        className: 'bold-number',
        element: BoldNumber,
    },
}

function getDisplayedType(filters: Partial<FilterType>): DisplayedType {
    return isRetentionFilter(filters)
        ? 'RetentionContainer'
        : isPathsFilter(filters)
        ? 'PathsContainer'
        : isFunnelsFilter(filters)
        ? 'FunnelContainer'
        : isFilterWithDisplay(filters)
        ? filters.display || ChartDisplayType.ActionsLineGraph
        : ChartDisplayType.ActionsLineGraph
}

export interface InsightCardProps extends Resizeable, React.HTMLAttributes<HTMLDivElement> {
    /** Insight to display. */
    insight: InsightModel
    /** id of the dashboard the card is on (when the card is being displayed on a dashboard) **/
    dashboardId?: DashboardType['id']
    /** Whether the insight has been called to load. */
    loadingQueued?: boolean
    /** Whether the insight is loading. */
    loading?: boolean
    /** Whether the insight likely showing stale data. */
    stale?: boolean
    /** Whether an error occurred on the server. */
    apiErrored?: boolean
    /** Whether the card should be highlighted with a blue border. */
    highlighted?: boolean
    /** Whether loading timed out. */
    timedOut?: boolean
    /** Whether the editing controls should be enabled or not. */
    showEditingControls?: boolean
    /** Whether the  controls for showing details should be enabled or not. */
    showDetailsControls?: boolean
    /** Layout of the card on a grid. */
    layout?: Layout
    ribbonColor?: InsightColor | null
    updateColor?: (newColor: DashboardTile['color']) => void
    removeFromDashboard?: () => void
    deleteWithUndo?: () => Promise<void>
    refresh?: () => void
    rename?: () => void
    duplicate?: () => void
    moveToDashboard?: (dashboard: DashboardBasicType) => void
    /** buttons to add to the "more" menu on the card**/
    moreButtons?: JSX.Element | null
    placement: DashboardPlacement | 'SavedInsightGrid'
    /** Priority for loading the insight, lower is earlier. */
    loadPriority?: number
    doNotLoad?: boolean
}

function VizComponentFallback(): JSX.Element {
    return <LemonBanner type="warning">Unknown insight display type</LemonBanner>
}

export interface FilterBasedCardContentProps
    extends Pick<InsightCardProps, 'insight' | 'loading' | 'apiErrored' | 'timedOut' | 'style' | 'stale'> {
    insightProps: InsightLogicProps
    tooFewFunnelSteps?: boolean
    validationError?: string | null
    empty?: boolean
    setAreDetailsShown?: React.Dispatch<React.SetStateAction<boolean>>
    /** pass in information from queries, e.g. what text to use for empty states*/
    context?: QueryContext
}

export function FilterBasedCardContent({
    insight,
    insightProps,
    loading,
    setAreDetailsShown,
    apiErrored,
    timedOut,
    empty,
    tooFewFunnelSteps,
    validationError,
    context,
    stale,
}: FilterBasedCardContentProps): JSX.Element {
    const displayedType = getDisplayedType(insight.filters)
    const VizComponent = displayMap[displayedType]?.element || VizComponentFallback
    const query: InsightQueryNode = filtersToQueryNode(insight.filters)
    const key = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query,
        key,
        cachedResults: getCachedResults(insightProps.cachedInsight, query),
        doNotLoad: insightProps.doNotLoad,
        loadPriority: insightProps.loadPriority,
        dataNodeCollectionId: insightVizDataCollectionId(insightProps, key),
    }
    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <div
                className="InsightCard__viz"
                onClick={
                    setAreDetailsShown
                        ? () => {
                              setAreDetailsShown?.(false)
                          }
                        : undefined
                }
            >
                {stale && !loading && <SpinnerOverlay mode="editing" />}
                {loading && <SpinnerOverlay />}
                {tooFewFunnelSteps ? (
                    <FunnelSingleStepState actionable={false} />
                ) : validationError ? (
                    <InsightValidationError query={query} detail={validationError} />
                ) : empty ? (
                    <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
                ) : !loading && timedOut ? (
                    <InsightTimeoutState />
                ) : apiErrored && !loading ? (
                    <InsightErrorState query={query} excludeDetail />
                ) : (
                    !apiErrored && <VizComponent inCardView={true} showPersonsModal={false} context={context} />
                )}
            </div>
        </BindLogic>
    )
}

function InsightCardInternal(
    {
        insight: legacyInsight,
        dashboardId,
        ribbonColor,
        loadingQueued,
        loading,
        stale,
        apiErrored,
        timedOut,
        highlighted,
        showResizeHandles,
        canResizeWidth,
        showEditingControls,
        showDetailsControls,
        updateColor,
        removeFromDashboard,
        deleteWithUndo,
        refresh,
        rename,
        duplicate,
        moveToDashboard,
        className,
        children,
        moreButtons,
        placement,
        loadPriority,
        doNotLoad,
        ...divProps
    }: InsightCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const insight = getQueryBasedInsightModel(legacyInsight)
    const { theme } = useValues(themeLogic)
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        dashboardId: dashboardId,
        cachedInsight: legacyInsight, // TODO: use query based insight here
        loadPriority,
        doNotLoad,
    }

    const { insightLoading } = useValues(insightLogic(insightLogicProps))
    const { insightDataLoading, useQueryDashboardCards } = useValues(insightDataLogic(insightLogicProps))
    const { hasFunnelResults } = useValues(funnelDataLogic(insightLogicProps))
    const { isFunnelWithEnoughSteps, validationError } = useValues(insightVizDataLogic(insightLogicProps))

    if (insightLoading || insightDataLoading) {
        loading = true
    }

    const [areDetailsShown, setAreDetailsShown] = useState(false)

    return (
        <div
            className={clsx('InsightCard border', highlighted && 'InsightCard--highlighted', className)}
            data-attr="insight-card"
            {...divProps}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ ...(divProps?.style ?? {}), ...(theme?.boxStyle ?? {}) }}
            ref={ref}
        >
            <ErrorBoundary>
                <BindLogic logic={insightLogic} props={insightLogicProps}>
                    <InsightMeta
                        insight={insight}
                        ribbonColor={ribbonColor}
                        dashboardId={dashboardId}
                        updateColor={updateColor}
                        removeFromDashboard={removeFromDashboard}
                        deleteWithUndo={deleteWithUndo}
                        refresh={refresh}
                        loading={loadingQueued || loading}
                        rename={rename}
                        duplicate={duplicate}
                        moveToDashboard={moveToDashboard}
                        areDetailsShown={areDetailsShown}
                        setAreDetailsShown={setAreDetailsShown}
                        showEditingControls={showEditingControls}
                        showDetailsControls={showDetailsControls}
                        moreButtons={moreButtons}
                    />
                    {legacyInsight.query || useQueryDashboardCards ? (
                        <div className="InsightCard__viz">
                            <Query
                                query={insight.query}
                                cachedResults={legacyInsight}
                                context={{
                                    insightProps: insightLogicProps,
                                }}
                                stale={stale}
                                readOnly
                                embedded
                            />
                        </div>
                    ) : (
                        <FilterBasedCardContent
                            insight={legacyInsight}
                            insightProps={insightLogicProps}
                            loading={loading}
                            stale={stale}
                            setAreDetailsShown={setAreDetailsShown}
                            apiErrored={apiErrored}
                            timedOut={timedOut}
                            empty={
                                legacyInsight.filters.insight === InsightType.FUNNELS &&
                                !hasFunnelResults &&
                                !apiErrored
                            }
                            tooFewFunnelSteps={
                                legacyInsight.filters.insight === InsightType.FUNNELS && !isFunnelWithEnoughSteps
                            }
                            validationError={validationError}
                        />
                    )}
                </BindLogic>
                {showResizeHandles && (
                    <>
                        {canResizeWidth ? <ResizeHandle1D orientation="vertical" /> : null}
                        <ResizeHandle1D orientation="horizontal" />
                        {canResizeWidth ? <ResizeHandle2D /> : null}
                    </>
                )}
                {children /* Extras, such as resize handles */}
            </ErrorBoundary>
        </div>
    )
}
export const InsightCard = React.forwardRef(InsightCardInternal) as typeof InsightCardInternal
