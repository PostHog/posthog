import './InsightCard.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import { QueriesUnsupportedHere } from 'lib/components/Cards/InsightCard/QueriesUnsupportedHere'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import React, { useState } from 'react'
import { Layout } from 'react-grid-layout'
import { Funnel } from 'scenes/funnels/Funnel'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import {
    FunnelSingleStepState,
    FunnelValidationError,
    InsightEmptyState,
    InsightErrorState,
    InsightTimeoutState,
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

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
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
    /** Whether the insight is loading. */
    loading?: boolean
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
}

function VizComponentFallback(): JSX.Element {
    return <LemonBanner type="warning">Unknown insight display type</LemonBanner>
}

export interface FilterBasedCardContentProps
    extends Pick<InsightCardProps, 'insight' | 'loading' | 'apiErrored' | 'timedOut' | 'style'> {
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
}: FilterBasedCardContentProps): JSX.Element {
    const displayedType = getDisplayedType(insight.filters)
    const VizComponent = displayMap[displayedType]?.element || VizComponentFallback
    const query: InsightQueryNode = filtersToQueryNode(insight.filters)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(insightProps.cachedInsight, query),
        doNotLoad: insightProps.doNotLoad,
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
                {loading && <SpinnerOverlay />}
                {tooFewFunnelSteps ? (
                    <FunnelSingleStepState actionable={false} />
                ) : validationError ? (
                    <FunnelValidationError detail={validationError} />
                ) : empty ? (
                    <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
                ) : !loading && timedOut ? (
                    <InsightTimeoutState isLoading={false} insightProps={{ dashboardItemId: undefined }} />
                ) : apiErrored && !loading ? (
                    <InsightErrorState excludeDetail />
                ) : (
                    !apiErrored && <VizComponent inCardView={true} showPersonsModal={false} context={context} />
                )}
            </div>
        </BindLogic>
    )
}

function InsightCardInternal(
    {
        insight,
        dashboardId,
        ribbonColor,
        loading,
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
        ...divProps
    }: InsightCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        dashboardId: dashboardId,
        cachedInsight: insight,
    }

    const { insightLoading } = useValues(insightLogic(insightLogicProps))
    const { insightDataLoading } = useValues(insightDataLogic(insightLogicProps))
    const { hasFunnelResults } = useValues(funnelDataLogic(insightLogicProps))
    const { isFunnelWithEnoughSteps, validationError } = useValues(insightVizDataLogic(insightLogicProps))

    let tooFewFunnelSteps = false
    let empty = false
    if (insight.filters.insight === InsightType.FUNNELS) {
        if (!isFunnelWithEnoughSteps) {
            tooFewFunnelSteps = true
        }
        if (!hasFunnelResults) {
            empty = true
        }
    }
    if (insightLoading || insightDataLoading) {
        loading = true
    }

    const [areDetailsShown, setAreDetailsShown] = useState(false)

    const canMakeQueryAPICalls =
        placement === 'SavedInsightGrid' ||
        [DashboardPlacement.Dashboard, DashboardPlacement.ProjectHomepage, DashboardPlacement.FeatureFlag].includes(
            placement
        )

    return (
        <div
            className={clsx('InsightCard border', highlighted && 'InsightCard--highlighted', className)}
            data-attr="insight-card"
            {...divProps}
            ref={ref}
        >
            <BindLogic logic={insightLogic} props={insightLogicProps}>
                <InsightMeta
                    insight={insight}
                    ribbonColor={ribbonColor}
                    dashboardId={dashboardId}
                    updateColor={updateColor}
                    removeFromDashboard={removeFromDashboard}
                    deleteWithUndo={deleteWithUndo}
                    refresh={refresh}
                    rename={rename}
                    duplicate={duplicate}
                    moveToDashboard={moveToDashboard}
                    areDetailsShown={areDetailsShown}
                    setAreDetailsShown={setAreDetailsShown}
                    showEditingControls={showEditingControls}
                    showDetailsControls={showDetailsControls}
                    moreButtons={moreButtons}
                />
                {insight.query ? (
                    <div className="InsightCard__viz">
                        {insight.result ? (
                            <Query query={insight.query} cachedResults={insight.result} readOnly />
                        ) : canMakeQueryAPICalls ? (
                            <Query query={insight.query} readOnly />
                        ) : (
                            <QueriesUnsupportedHere />
                        )}
                    </div>
                ) : insight.filters?.insight ? (
                    <FilterBasedCardContent
                        insight={insight}
                        insightProps={insightLogicProps}
                        loading={loading}
                        apiErrored={apiErrored}
                        timedOut={timedOut}
                        empty={empty}
                        tooFewFunnelSteps={tooFewFunnelSteps}
                        validationError={validationError}
                        setAreDetailsShown={setAreDetailsShown}
                    />
                ) : (
                    <div className="flex justify-between items-center h-full">
                        <InsightErrorState
                            excludeDetail
                            title="Missing 'filters.insight' property, can't display insight"
                        />
                    </div>
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
        </div>
    )
}
export const InsightCard = React.forwardRef(InsightCardInternal) as typeof InsightCardInternal
