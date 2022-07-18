import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { capitalizeFirstLetter, dateFilterToText, Loading } from 'lib/utils'
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
    DashboardType,
    FilterType,
    InsightColor,
    InsightLogicProps,
    InsightModel,
    InsightType,
} from '~/types'
import { Splotch, SplotchColor } from '../icons/Splotch'
import { LemonButton, LemonButtonWithPopup } from '../LemonButton'
import { More } from '../LemonButton/More'
import { LemonDivider } from '../LemonDivider'
import { Link } from '../Link'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ResizeHandle1D, ResizeHandle2D } from './handles'
import './InsightCard.scss'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { IconSubtitles, IconSubtitlesOff } from '../icons'
import { CSSTransition, Transition } from 'react-transition-group'
import { InsightDetails } from './InsightDetails'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { DashboardPrivilegeLevel } from 'lib/constants'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionsHorizontalBar, ActionsLineGraph, ActionsPie } from 'scenes/trends/viz'
import { DashboardInsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { Funnel } from 'scenes/funnels/Funnel'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { Paths } from 'scenes/paths/Paths'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { summarizeInsightFilters } from 'scenes/insights/utils'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { WorldMap } from 'scenes/insights/views/WorldMap'
import { AlertMessage } from '../AlertMessage'
import { UserActivityIndicator } from '../UserActivityIndicator/UserActivityIndicator'

// TODO: Add support for Retention to InsightDetails
export const INSIGHT_TYPES_WHERE_DETAILS_UNSUPPORTED: InsightType[] = [InsightType.RETENTION]

type DisplayedType = ChartDisplayType | 'RetentionContainer'

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
    FunnelViz: {
        className: 'funnel',
        element: Funnel,
    },
    RetentionContainer: {
        className: 'retention',
        element: RetentionContainer,
    },
    PathsViz: {
        className: 'paths-viz',
        element: Paths,
    },
    WorldMap: {
        className: 'world-map',
        element: WorldMap,
    },
}

function getDisplayedType(filters: Partial<FilterType>): DisplayedType {
    return (
        filters.insight === InsightType.RETENTION
            ? 'RetentionContainer'
            : filters.insight === InsightType.PATHS
            ? 'PathsViz'
            : filters.insight === InsightType.FUNNELS
            ? 'FunnelViz'
            : filters.display || 'ActionsLineGraph'
    ) as DisplayedType
}

export interface InsightCardProps extends React.HTMLAttributes<HTMLDivElement> {
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
    showResizeHandles?: boolean
    canResizeWidth?: boolean
    /** Whether the editing controls should be enabled or not. */
    showEditingControls?: boolean
    /** Whether the  controls for showing details should be enabled or not. */
    showDetailsControls?: boolean
    /** Layout of the card on a grid. */
    layout?: Layout
    updateColor?: (newColor: InsightModel['color']) => void
    removeFromDashboard?: () => void
    deleteWithUndo?: () => void
    refresh?: () => void
    rename?: () => void
    duplicate?: () => void
    moveToDashboard?: (dashboard: DashboardType) => void
}

interface InsightMetaProps
    extends Pick<
        InsightCardProps,
        | 'insight'
        | 'updateColor'
        | 'removeFromDashboard'
        | 'deleteWithUndo'
        | 'refresh'
        | 'rename'
        | 'duplicate'
        | 'moveToDashboard'
        | 'showEditingControls'
        | 'showDetailsControls'
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
}: InsightMetaProps): JSX.Element {
    const { short_id, name, description, tags, color, filters, dashboards } = insight

    const { reportDashboardItemRefreshed } = useActions(eventUsageLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { mathDefinitions } = useValues(mathsLogic)
    const otherDashboards: DashboardType[] = nameSortedDashboards.filter(
        (d: DashboardType) => !dashboards?.includes(d.id)
    )

    const { ref: primaryRef, height: primaryHeight, width: primaryWidth } = useResizeObserver()
    const { ref: detailsRef, height: detailsHeight } = useResizeObserver()

    useEffect(() => {
        setPrimaryHeight?.(primaryHeight)
    }, [primaryHeight])

    const areDetailsSupported = !INSIGHT_TYPES_WHERE_DETAILS_UNSUPPORTED.includes(
        insight.filters.insight || InsightType.TRENDS
    )
    const showDetailsButtonLabel = !!primaryWidth && primaryWidth > 480

    const editable = insight.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit
    const foldedHeight = `calc(${primaryHeight}px + 2rem /* margins */ + 1px /* border */)`
    const unfoldedHeight = `calc(${primaryHeight}px + ${
        detailsHeight || 0
    }px + 3.5rem /* margins */ + 3px /* border and spacer */)`
    const transitionStyles = primaryHeight
        ? {
              entering: {
                  height: unfoldedHeight,
              },
              entered: {
                  height: unfoldedHeight,
              },
              exiting: { height: foldedHeight },
              exited: { height: foldedHeight },
          }
        : {}

    return (
        <CSSTransition in={areDetailsShown} timeout={200} classNames="InsightMeta--expansion">
            {(transitionState) => (
                <div className="InsightMeta" style={transitionStyles[transitionState]}>
                    <div className="InsightMeta__primary" ref={primaryRef}>
                        {color &&
                            color !==
                                InsightColor.White /* White has historically meant no color synonymously to null */ && (
                                <div className={clsx('InsightMeta__ribbon', color)} />
                            )}
                        <div className="InsightMeta__main">
                            <div className="InsightMeta__top">
                                <h5>
                                    <span
                                        title={
                                            INSIGHT_TYPES_METADATA[filters.insight || InsightType.TRENDS]?.description
                                        }
                                    >
                                        {INSIGHT_TYPES_METADATA[filters.insight || InsightType.TRENDS]?.name}
                                    </span>{' '}
                                    • {dateFilterToText(filters.date_from, filters.date_to, 'Last 7 days')}
                                </h5>
                                <div className="InsightMeta__controls">
                                    {areDetailsSupported && showDetailsControls && setAreDetailsShown && (
                                        <LemonButton
                                            icon={!areDetailsShown ? <IconSubtitles /> : <IconSubtitlesOff />}
                                            onClick={() => setAreDetailsShown((state) => !state)}
                                            type="tertiary"
                                            size={showDetailsButtonLabel ? 'small' : undefined}
                                        >
                                            {showDetailsButtonLabel && `${!areDetailsShown ? 'Show' : 'Hide'} details`}
                                        </LemonButton>
                                    )}
                                    {showEditingControls && (
                                        <More
                                            overlay={
                                                <>
                                                    <LemonButton
                                                        type="stealth"
                                                        to={urls.insightView(short_id)}
                                                        fullWidth
                                                    >
                                                        View
                                                    </LemonButton>
                                                    {refresh && (
                                                        <LemonButton
                                                            type="stealth"
                                                            onClick={() => {
                                                                refresh()
                                                                reportDashboardItemRefreshed(insight)
                                                            }}
                                                            fullWidth
                                                        >
                                                            Refresh
                                                        </LemonButton>
                                                    )}
                                                    {editable && updateColor && (
                                                        <LemonButtonWithPopup
                                                            type="stealth"
                                                            popup={{
                                                                overlay: Object.values(InsightColor).map(
                                                                    (availableColor) => (
                                                                        <LemonButton
                                                                            key={availableColor}
                                                                            type={
                                                                                availableColor ===
                                                                                (color || InsightColor.White)
                                                                                    ? 'highlighted'
                                                                                    : 'stealth'
                                                                            }
                                                                            onClick={() => updateColor(availableColor)}
                                                                            icon={
                                                                                availableColor !==
                                                                                InsightColor.White ? (
                                                                                    <Splotch
                                                                                        color={
                                                                                            availableColor as string as SplotchColor
                                                                                        }
                                                                                    />
                                                                                ) : null
                                                                            }
                                                                            fullWidth
                                                                        >
                                                                            {availableColor !== InsightColor.White
                                                                                ? capitalizeFirstLetter(availableColor)
                                                                                : 'No color'}
                                                                        </LemonButton>
                                                                    )
                                                                ),
                                                                placement: 'right-start',
                                                                fallbackPlacements: ['left-start'],
                                                                actionable: true,
                                                            }}
                                                            fullWidth
                                                        >
                                                            Set color
                                                        </LemonButtonWithPopup>
                                                    )}
                                                    {editable && moveToDashboard && otherDashboards.length > 0 && (
                                                        <LemonButtonWithPopup
                                                            type="stealth"
                                                            popup={{
                                                                overlay: otherDashboards.map((otherDashboard) => (
                                                                    <LemonButton
                                                                        key={otherDashboard.id}
                                                                        type="stealth"
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
                                                            }}
                                                            fullWidth
                                                        >
                                                            Move to
                                                        </LemonButtonWithPopup>
                                                    )}
                                                    <LemonDivider />
                                                    {editable && (
                                                        <LemonButton
                                                            type="stealth"
                                                            to={urls.insightEdit(short_id)}
                                                            fullWidth
                                                        >
                                                            Edit
                                                        </LemonButton>
                                                    )}
                                                    {editable && (
                                                        <LemonButton type="stealth" onClick={rename} fullWidth>
                                                            Rename
                                                        </LemonButton>
                                                    )}
                                                    <LemonButton type="stealth" onClick={duplicate} fullWidth>
                                                        Duplicate
                                                    </LemonButton>
                                                    {editable && (
                                                        <>
                                                            <LemonDivider />
                                                            {removeFromDashboard ? (
                                                                <LemonButton
                                                                    type="stealth"
                                                                    status="danger"
                                                                    onClick={removeFromDashboard}
                                                                    fullWidth
                                                                >
                                                                    Remove from dashboard
                                                                </LemonButton>
                                                            ) : (
                                                                <LemonButton
                                                                    type="stealth"
                                                                    status="danger"
                                                                    onClick={deleteWithUndo}
                                                                    fullWidth
                                                                >
                                                                    Delete insight
                                                                </LemonButton>
                                                            )}
                                                        </>
                                                    )}
                                                </>
                                            }
                                        />
                                    )}
                                </div>
                            </div>
                            <Link to={urls.insightView(short_id)}>
                                <h4 title={name} data-attr="insight-card-title">
                                    {name || (
                                        <i>
                                            {summarizeInsightFilters(
                                                filters,
                                                aggregationLabel,
                                                cohortsById,
                                                mathDefinitions
                                            )}
                                        </i>
                                    )}
                                </h4>
                            </Link>
                            <div className="InsightMeta__description">{description || <i>No description</i>}</div>
                            {tags && tags.length > 0 && <ObjectTags tags={tags} staticOnly />}
                            <UserActivityIndicator at={insight.last_modified_at} by={insight.last_modified_by} />
                        </div>
                    </div>
                    <LemonDivider />
                    <Transition in={areDetailsShown} timeout={200} mountOnEnter unmountOnExit>
                        <InsightDetails insight={insight} ref={detailsRef} />
                    </Transition>
                </div>
            )}
        </CSSTransition>
    )
}

function VizComponentFallback(): JSX.Element {
    return (
        <AlertMessage type="warning" style={{ alignSelf: 'center' }}>
            Unknown insight display type
        </AlertMessage>
    )
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

    return (
        <div
            className="InsightViz"
            style={style}
            onClick={
                setAreDetailsShown
                    ? () => {
                          setAreDetailsShown?.(false)
                      }
                    : undefined
            }
        >
            {loading && !timedOut && <Loading />}
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

    const { showTimeoutMessage, showErrorMessage, insightLoading } = useValues(insightLogic(insightLogicProps))
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
    if (showErrorMessage) {
        apiErrored = true
    }
    if (showTimeoutMessage) {
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
                />
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
                            ? { height: `calc(100% - ${metaPrimaryHeight}px - 2rem /* margins */ - 1px /* border */)` }
                            : undefined
                    }
                    setAreDetailsShown={setAreDetailsShown}
                />
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
