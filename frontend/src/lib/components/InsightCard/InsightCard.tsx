import { Alert } from 'antd'
import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { capitalizeFirstLetter, dateFilterToText, Loading } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import { Layout } from 'react-grid-layout'
import { displayMap, getDisplayedType } from 'scenes/dashboard/DashboardItem'
import { UNNAMED_INSIGHT_NAME } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType, InsightColor, InsightLogicProps, InsightModel, InsightType } from '~/types'
import { Splotch, SplotchColor } from '../icons/Splotch'
import { LemonButton, LemonButtonWithPopup } from '../LemonButton'
import { More } from '../LemonButton/More'
import { LemonSpacer } from '../LemonRow'
import { Link } from '../Link'
import { ObjectTags } from '../ObjectTags'
import { ResizeHandle1D, ResizeHandle2D } from './handles'
import { LastModified } from './LastModified'
import './InsightCard.scss'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { IconSubtitles, IconSubtitlesOff } from '../icons'
import { CSSTransition, Transition } from 'react-transition-group'
import { InsightDetails } from './InsightDetails'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

export interface InsightCardProps extends React.HTMLAttributes<HTMLDivElement> {
    /** Insight to display. */
    insight: InsightModel
    /** Whether the insight is loading. */
    loading?: boolean
    /** Whether loading the insight resulted in an error. */
    apiError?: boolean
    /** Whether the card should be highlighted with a blue border. */
    highlighted?: boolean
    showResizeHandles?: boolean
    /** Layout of the card on a grid. */
    layout?: Layout
    updateColor?: (newColor: InsightModel['color']) => void
    removeFromDashboard?: () => void
    deleteWithUndo?: () => void
    refresh?: () => void
    rename: () => void
    duplicate: () => void
    moveToDashboard?: (dashboardId: DashboardType['id']) => void
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
}: InsightMetaProps): JSX.Element {
    const { short_id, name, description, tags, color, filters, dashboard } = insight

    const { nameSortedDashboards } = useValues(dashboardsModel)
    const otherDashboards: DashboardType[] = nameSortedDashboards.filter((d: DashboardType) => d.id !== dashboard)

    const { ref: primaryRef, height: primaryHeight } = useResizeObserver()
    const { ref: detailsRef, height: detailsHeight } = useResizeObserver()

    useEffect(() => {
        setPrimaryHeight?.(primaryHeight)
    }, [primaryHeight])

    const transitionStyles = primaryHeight
        ? {
              entering: {
                  height: `calc(${primaryHeight}px + ${
                      detailsHeight || 0
                  }px + 3.5rem /* margins */ + 2px /* border and spacer */)`,
              },
              entered: {
                  height: `calc(${primaryHeight}px + ${
                      detailsHeight || 0
                  }px + 3.5rem /* margins */ + 2px /* border and spacer */)`,
              },
              exiting: { height: `calc(${primaryHeight}px + 2rem /* margins */ + 1px /* border */)` },
              exited: { height: `calc(${primaryHeight}px + 2rem /* margins */ + 1px /* border */)` },
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
                                            INSIGHT_TYPES_METADATA[filters.insight || InsightType.TRENDS].description
                                        }
                                    >
                                        {INSIGHT_TYPES_METADATA[filters.insight || InsightType.TRENDS].name}
                                    </span>{' '}
                                    • {dateFilterToText(filters.date_from, filters.date_to, 'Last 7 days')}
                                </h5>
                                <div className="InsightMeta__controls">
                                    {setAreDetailsShown && (
                                        <LemonButton
                                            icon={!areDetailsShown ? <IconSubtitles /> : <IconSubtitlesOff />}
                                            onClick={() => setAreDetailsShown((state) => !state)}
                                            type="tertiary"
                                            compact
                                        >
                                            {!areDetailsShown ? 'Show' : 'Hide'} details
                                        </LemonButton>
                                    )}
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton type="stealth" to={urls.insightView(short_id)} fullWidth>
                                                    View
                                                </LemonButton>
                                                {refresh && (
                                                    <LemonButton type="stealth" onClick={() => refresh()} fullWidth>
                                                        Refresh
                                                    </LemonButton>
                                                )}
                                                {updateColor && (
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
                                                                            availableColor !== InsightColor.White ? (
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
                                                {moveToDashboard && otherDashboards.length > 0 && (
                                                    <LemonButtonWithPopup
                                                        type="stealth"
                                                        popup={{
                                                            overlay: otherDashboards.map((otherDashboard) => (
                                                                <LemonButton
                                                                    key={otherDashboard.id}
                                                                    type="stealth"
                                                                    onClick={() => moveToDashboard(otherDashboard.id)}
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
                                                <LemonSpacer />
                                                <LemonButton type="stealth" to={urls.insightEdit(short_id)} fullWidth>
                                                    Edit
                                                </LemonButton>
                                                <LemonButton type="stealth" onClick={rename} fullWidth>
                                                    Rename
                                                </LemonButton>
                                                <LemonButton type="stealth" onClick={duplicate} fullWidth>
                                                    Duplicate
                                                </LemonButton>
                                                <LemonSpacer />
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
                                        }
                                    />
                                </div>
                            </div>
                            <Link to={urls.insightView(short_id)}>
                                <h4 title={name} data-attr="insight-card-title">
                                    {name || <i>{UNNAMED_INSIGHT_NAME}</i>}
                                </h4>
                            </Link>
                            <div className="InsightMeta__description">{description || <i>No description</i>}</div>
                            {tags.length > 0 && <ObjectTags tags={tags} staticOnly />}
                            <LastModified at={insight.last_modified_at} by={insight.last_modified_by} />
                        </div>
                    </div>
                    <LemonSpacer />
                    <Transition in={areDetailsShown} timeout={200} mountOnEnter unmountOnExit>
                        <InsightDetails insight={insight} ref={detailsRef} />
                    </Transition>
                </div>
            )}
        </CSSTransition>
    )
}

interface InsightVizProps extends Pick<InsightCardProps, 'insight' | 'loading' | 'apiError' | 'style'> {
    setAreDetailsShown?: React.Dispatch<React.SetStateAction<boolean>>
}

function InsightViz({ insight, loading, setAreDetailsShown, style }: InsightVizProps): JSX.Element {
    const { short_id, filters, result: cachedResults } = insight

    const displayedType = getDisplayedType(filters)
    const VizComponent = displayMap[displayedType].element

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
            {loading && <Loading />}
            <Alert.ErrorBoundary message="Insight visualization errored. We're sorry for the interruption.">
                <VizComponent dashboardItemId={short_id} cachedResults={cachedResults} filters={filters} />
            </Alert.ErrorBoundary>
        </div>
    )
}

function InsightCardInternal(
    {
        insight,
        loading,
        apiError,
        highlighted,
        showResizeHandles,
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
    const { short_id, filters, result: cachedResults } = insight

    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: short_id,
        filters,
        cachedResults,
        doNotLoad: true,
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
            <InsightMeta
                insight={insight}
                updateColor={updateColor}
                removeFromDashboard={removeFromDashboard}
                deleteWithUndo={deleteWithUndo}
                refresh={refresh}
                rename={rename}
                duplicate={duplicate}
                moveToDashboard={moveToDashboard}
            />
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
                />
                <InsightViz
                    insight={insight}
                    loading={loading}
                    apiError={apiError}
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
                    <ResizeHandle1D orientation="vertical" />
                    <ResizeHandle1D orientation="horizontal" />
                    <ResizeHandle2D />
                </>
            )}
            {children /* Extras, such as resize handles */}
        </div>
    )
}
export const InsightCard = React.forwardRef(InsightCardInternal) as typeof InsightCardInternal
