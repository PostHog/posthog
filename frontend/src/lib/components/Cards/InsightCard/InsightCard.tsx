import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { capitalizeFirstLetter, dateFilterToText } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import { Layout } from 'react-grid-layout'
import {
    FunnelInvalidExclusionState,
    FunnelSingleStepState,
    InsightEmptyState,
    InsightErrorState,
    InsightTimeoutState,
} from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import {
    ChartDisplayType,
    ChartParams,
    DashboardTile,
    DashboardType,
    ExporterFormat,
    FilterType,
    InsightColor,
    InsightLogicProps,
    InsightModel,
    InsightType,
} from '~/types'
import { Splotch, SplotchColor } from 'lib/lemon-ui/Splotch'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Link } from 'lib/lemon-ui/Link'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ResizeHandle1D, ResizeHandle2D } from '../handles'
import './InsightCard.scss'
import { InsightDetails } from './InsightDetails'
import { InsightTypeMetadata, INSIGHT_TYPES_METADATA, QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionsHorizontalBar, ActionsLineGraph, ActionsPie } from 'scenes/trends/viz'
import { DashboardInsightsTable } from 'scenes/insights/views/InsightsTable/DashboardInsightsTable'
import { Funnel } from 'scenes/funnels/Funnel'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { Paths } from 'scenes/paths/Paths'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { summarizeInsightFilters, summarizeInsightQuery } from 'scenes/insights/utils'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { WorldMap } from 'scenes/insights/views/WorldMap'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { UserActivityIndicator } from '../../UserActivityIndicator/UserActivityIndicator'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { BoldNumber } from 'scenes/insights/views/BoldNumber'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import {
    isFilterWithDisplay,
    isFunnelsFilter,
    isPathsFilter,
    isRetentionFilter,
    isTrendsFilter,
} from 'scenes/insights/sharedUtils'
import { CardMeta, Resizeable } from 'lib/components/Cards/Card'
import { DashboardPrivilegeLevel } from 'lib/constants'
import { Query } from '~/queries/Query/Query'
import { dateRangeFor, isInsightQueryNode, isInsightVizNode } from '~/queries/utils'
import { InsightVizNode } from '~/queries/schema'

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
    const displayedType: DisplayedType = isRetentionFilter(filters)
        ? 'RetentionContainer'
        : isPathsFilter(filters)
        ? 'PathsContainer'
        : isFunnelsFilter(filters)
        ? 'FunnelContainer'
        : isFilterWithDisplay(filters)
        ? filters.display || ChartDisplayType.ActionsLineGraph
        : ChartDisplayType.ActionsLineGraph
    return displayedType
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
    deleteWithUndo?: () => void
    refresh?: () => void
    rename?: () => void
    duplicate?: () => void
    moveToDashboard?: (dashboard: DashboardType) => void
    /** buttons to add to the "more" menu on the card**/
    moreButtons?: JSX.Element | null
}

interface InsightMetaProps
    extends Pick<
        InsightCardProps,
        | 'insight'
        | 'ribbonColor'
        | 'updateColor'
        | 'removeFromDashboard'
        | 'deleteWithUndo'
        | 'refresh'
        | 'rename'
        | 'duplicate'
        | 'dashboardId'
        | 'moveToDashboard'
        | 'showEditingControls'
        | 'showDetailsControls'
        | 'moreButtons'
    > {
    /**
     * Optional callback to update height of the primary InsightMeta div. Allow for coordinating InsightViz height
     * with InsightMeta in a way that makes it possible for meta to overlay viz in expanded (InsightDetails) state.
     */
    setPrimaryHeight?: (primaryHeight: number | undefined) => void
    areDetailsShown?: boolean
    setAreDetailsShown?: React.Dispatch<React.SetStateAction<boolean>>
}

function InsightMeta({
    insight,
    ribbonColor,
    dashboardId,
    updateColor,
    removeFromDashboard,
    deleteWithUndo,
    refresh,
    rename,
    duplicate,
    moveToDashboard,
    setPrimaryHeight,
    areDetailsShown,
    setAreDetailsShown,
    showEditingControls = true,
    showDetailsControls = true,
    moreButtons,
}: InsightMetaProps): JSX.Element {
    const { short_id, name, filters, dashboards } = insight
    const { exporterResourceParams, insightProps } = useValues(insightLogic)
    const { reportDashboardItemRefreshed } = useActions(eventUsageLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { mathDefinitions } = useValues(mathsLogic)
    const otherDashboards: DashboardType[] = nameSortedDashboards.filter(
        (d: DashboardType) => !dashboards?.includes(d.id)
    )
    const editable = insight.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit

    // not all interactions are currently implemented for queries
    const allInteractionsAllowed = !insight.query

    const summary = !!name
        ? null
        : !!Object.keys(insight.filters).length
        ? summarizeInsightFilters(filters, aggregationLabel, cohortsById, mathDefinitions)
        : !!insight.query
        ? isInsightVizNode(insight.query)
            ? summarizeInsightQuery(
                  (insight.query as InsightVizNode).source,
                  aggregationLabel,
                  cohortsById,
                  mathDefinitions
              )
            : // TODO summarise other kinds of query too
              'query: ' + insight.query.kind
        : null

    return (
        <CardMeta
            setPrimaryHeight={setPrimaryHeight}
            ribbonColor={ribbonColor}
            showEditingControls={showEditingControls}
            showDetailsControls={showDetailsControls}
            setAreDetailsShown={setAreDetailsShown}
            areDetailsShown={areDetailsShown}
            className={'border-b'}
            topHeading={<TopHeading insight={insight} />}
            meta={
                <>
                    <Link to={urls.insightView(short_id)}>
                        <h4 title={name} data-attr="insight-card-title">
                            {name || <i>{summary}</i>}
                        </h4>
                    </Link>

                    {!!insight.description && <div className="CardMeta__description">{insight.description}</div>}
                    {insight.tags && insight.tags.length > 0 && <ObjectTags tags={insight.tags} staticOnly />}
                    <UserActivityIndicator at={insight.last_modified_at} by={insight.last_modified_by} />
                </>
            }
            metaDetails={<InsightDetails insight={insight} />}
            moreButtons={
                <>
                    {allInteractionsAllowed && (
                        <>
                            <LemonButton status="stealth" to={urls.insightView(short_id)} fullWidth>
                                View
                            </LemonButton>
                            {refresh && (
                                <LemonButton
                                    status="stealth"
                                    onClick={() => {
                                        refresh()
                                        reportDashboardItemRefreshed(insight)
                                    }}
                                    fullWidth
                                >
                                    Refresh
                                </LemonButton>
                            )}
                        </>
                    )}
                    {editable && updateColor && (
                        <LemonButtonWithDropdown
                            status="stealth"
                            dropdown={{
                                overlay: Object.values(InsightColor).map((availableColor) => (
                                    <LemonButton
                                        key={availableColor}
                                        active={availableColor === (ribbonColor || InsightColor.White)}
                                        status="stealth"
                                        onClick={() => updateColor(availableColor)}
                                        icon={
                                            availableColor !== InsightColor.White ? (
                                                <Splotch color={availableColor as string as SplotchColor} />
                                            ) : null
                                        }
                                        fullWidth
                                    >
                                        {availableColor !== InsightColor.White
                                            ? capitalizeFirstLetter(availableColor)
                                            : 'No color'}
                                    </LemonButton>
                                )),
                                placement: 'right-start',
                                fallbackPlacements: ['left-start'],
                                actionable: true,
                                closeParentPopoverOnClickInside: true,
                            }}
                            fullWidth
                        >
                            Set color
                        </LemonButtonWithDropdown>
                    )}
                    {editable && moveToDashboard && otherDashboards.length > 0 && (
                        <LemonButtonWithDropdown
                            status="stealth"
                            dropdown={{
                                overlay: otherDashboards.map((otherDashboard) => (
                                    <LemonButton
                                        key={otherDashboard.id}
                                        status="stealth"
                                        onClick={() => {
                                            moveToDashboard(otherDashboard)
                                        }}
                                        fullWidth
                                    >
                                        {otherDashboard.name || <i>Untitled</i>}
                                    </LemonButton>
                                )),
                                placement: 'right-start',
                                fallbackPlacements: ['left-start'],
                                actionable: true,
                                closeParentPopoverOnClickInside: true,
                            }}
                            fullWidth
                        >
                            Move to
                        </LemonButtonWithDropdown>
                    )}
                    <LemonDivider />
                    {editable && allInteractionsAllowed && (
                        <LemonButton status="stealth" to={urls.insightEdit(short_id)} fullWidth>
                            Edit
                        </LemonButton>
                    )}
                    {editable && (
                        <LemonButton status="stealth" onClick={rename} fullWidth>
                            Rename
                        </LemonButton>
                    )}
                    <LemonButton
                        status="stealth"
                        onClick={duplicate}
                        fullWidth
                        data-attr={
                            dashboardId ? 'duplicate-insight-from-dashboard' : 'duplicate-insight-from-card-list-view'
                        }
                    >
                        Duplicate
                    </LemonButton>
                    <LemonDivider />
                    {exporterResourceParams ? (
                        <ExportButton
                            fullWidth
                            items={[
                                {
                                    export_format: ExporterFormat.PNG,
                                    insight: insight.id,
                                    dashboard: insightProps.dashboardId,
                                },
                                {
                                    export_format: ExporterFormat.CSV,
                                    export_context: exporterResourceParams,
                                },
                            ]}
                        />
                    ) : null}
                    {moreButtons && (
                        <>
                            <LemonDivider />
                            {moreButtons}
                        </>
                    )}
                    {editable && (
                        <>
                            <LemonDivider />
                            {removeFromDashboard ? (
                                <LemonButton status="danger" onClick={removeFromDashboard} fullWidth>
                                    Remove from dashboard
                                </LemonButton>
                            ) : allInteractionsAllowed ? (
                                <LemonButton status="danger" onClick={deleteWithUndo} fullWidth>
                                    Delete insight
                                </LemonButton>
                            ) : null}
                        </>
                    )}
                </>
            }
        />
    )
}

function TopHeading({ insight }: { insight: InsightModel }): JSX.Element {
    const { filters, query } = insight

    let insightType: InsightTypeMetadata

    // check the query first because the backend still adds defaults to empty filters :/
    if (!!query?.kind) {
        insightType = QUERY_TYPES_METADATA[query.kind]
    } else if (!!filters.insight) {
        insightType = INSIGHT_TYPES_METADATA[filters.insight]
    } else {
        // maintain the existing default
        insightType = INSIGHT_TYPES_METADATA[InsightType.TRENDS]
    }

    let { date_from, date_to } = filters
    if (!!query) {
        const queryDateRange = dateRangeFor(query)
        if (!!queryDateRange) {
            date_from = queryDateRange.date_from
            date_to = queryDateRange.date_to
        }
    }

    const defaultDateRange = query == undefined || isInsightQueryNode(query) ? 'Last 7 days' : null
    return (
        <>
            <span title={insightType?.description}>{insightType?.name}</span> •{' '}
            {dateFilterToText(date_from, date_to, defaultDateRange)}
        </>
    )
}

function VizComponentFallback(): JSX.Element {
    return <AlertMessage type="warning">Unknown insight display type</AlertMessage>
}

export interface InsightVizProps
    extends Pick<InsightCardProps, 'insight' | 'loading' | 'apiErrored' | 'timedOut' | 'style'> {
    tooFewFunnelSteps?: boolean
    invalidFunnelExclusion?: boolean
    empty?: boolean
    setAreDetailsShown?: React.Dispatch<React.SetStateAction<boolean>>
}

export function InsightViz({
    insight,
    loading,
    setAreDetailsShown,
    style,
    apiErrored,
    timedOut,
    empty,
    tooFewFunnelSteps,
    invalidFunnelExclusion,
}: InsightVizProps): JSX.Element {
    const displayedType = getDisplayedType(insight.filters)
    const VizComponent = displayMap[displayedType]?.element || VizComponentFallback

    useEffect(() => {
        // If displaying a BoldNumber Trends insight, we need to fire the window resize event
        // Without this, the value is only autosized before `metaPrimaryHeight` is determined, so it's wrong
        // With this, autosizing runs again after `metaPrimaryHeight` is ready
        if (
            // `display` should be ignored in non-Trends insight
            isTrendsFilter(insight.filters) &&
            insight.filters.display === ChartDisplayType.BoldNumber
        ) {
            window.dispatchEvent(new Event('resize'))
        }
    }, [style?.height])

    return (
        <div
            className="InsightViz"
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            onClick={
                setAreDetailsShown
                    ? () => {
                          setAreDetailsShown?.(false)
                      }
                    : undefined
            }
        >
            {loading && !timedOut && <SpinnerOverlay />}
            {tooFewFunnelSteps ? (
                <FunnelSingleStepState actionable={false} />
            ) : invalidFunnelExclusion ? (
                <FunnelInvalidExclusionState />
            ) : empty ? (
                <InsightEmptyState />
            ) : timedOut ? (
                <InsightTimeoutState isLoading={!!loading} />
            ) : apiErrored && !loading ? (
                <InsightErrorState excludeDetail />
            ) : (
                !apiErrored && <VizComponent inCardView={true} showPersonsModal={false} />
            )}
        </div>
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
        ...divProps
    }: InsightCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        dashboardId: dashboardId,
        cachedInsight: insight,
        doNotLoad: true,
    }

    const { timedOutQueryId, erroredQueryId, insightLoading } = useValues(insightLogic(insightLogicProps))
    const { areFiltersValid, isValidFunnel, areExclusionFiltersValid } = useValues(funnelLogic(insightLogicProps))

    let tooFewFunnelSteps = false
    let invalidFunnelExclusion = false
    let empty = false
    if (insight.filters.insight === InsightType.FUNNELS) {
        if (!areFiltersValid) {
            tooFewFunnelSteps = true
        } else if (!areExclusionFiltersValid) {
            invalidFunnelExclusion = true
        }
        if (!isValidFunnel) {
            empty = true
        }
    }
    if (insightLoading) {
        loading = true
    }
    if (!!erroredQueryId) {
        apiErrored = true
    }
    if (!!timedOutQueryId) {
        timedOut = true
    }

    const [metaPrimaryHeight, setMetaPrimaryHeight] = useState<number | undefined>(undefined)
    const [areDetailsShown, setAreDetailsShown] = useState(false)

    return (
        <div
            className={clsx('InsightCard', highlighted && 'InsightCard--highlighted', className)}
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
                    setPrimaryHeight={setMetaPrimaryHeight}
                    areDetailsShown={areDetailsShown}
                    setAreDetailsShown={setAreDetailsShown}
                    showEditingControls={showEditingControls}
                    showDetailsControls={showDetailsControls}
                    moreButtons={moreButtons}
                />
                {!!insight.query ? (
                    <div
                        className="InsightViz p-2"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            metaPrimaryHeight
                                ? {
                                      height: `calc(100% - ${metaPrimaryHeight}px - 2rem /* margins */ - 1px /* border */)`,
                                  }
                                : undefined
                        }
                    >
                        <Query query={insight.query} />
                    </div>
                ) : (
                    <InsightViz
                        insight={insight}
                        loading={loading}
                        apiErrored={apiErrored}
                        timedOut={timedOut}
                        empty={empty}
                        tooFewFunnelSteps={tooFewFunnelSteps}
                        invalidFunnelExclusion={invalidFunnelExclusion}
                        style={
                            metaPrimaryHeight
                                ? {
                                      height: `calc(100% - ${metaPrimaryHeight}px - 2rem /* margins */ - 1px /* border */)`,
                                  }
                                : undefined
                        }
                        setAreDetailsShown={setAreDetailsShown}
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
        </div>
    )
}
export const InsightCard = React.forwardRef(InsightCardInternal) as typeof InsightCardInternal
