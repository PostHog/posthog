import './DashboardItems.scss'

import clsx from 'clsx'
import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'
import { RefObject, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Responsive as ReactGridLayout } from 'react-grid-layout'
import type { Layout, LayoutItem } from 'react-grid-layout'

import { DashboardWidgetItem } from '@posthog/products-dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem'
import { getDashboardWidgetFetchDisplayError } from '@posthog/products-dashboards/frontend/widgets/constants'

import { ApiError } from 'lib/api'
import { EditModeEdge, useResizeHandleScrollbarPassThrough } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { TileDecorations } from 'lib/components/TileDecorations/TileDecorations'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { objectsEqual } from 'lib/utils/objects'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import {
    BREAKPOINTS,
    BREAKPOINT_COLUMN_COUNTS,
    getInsightQueryError,
    isWidgetTileVisibleOnPlacement,
} from 'scenes/dashboard/dashboardUtils'
import {
    continueDragGestureInEditMode,
    continueResizeGestureInEditMode,
    whenPressBecomesDrag,
} from 'scenes/dashboard/editLayoutGesture'
import { useDashboardLayoutInteraction } from 'scenes/dashboard/useDashboardLayoutInteraction'
import { useSurveyLinkedInsights } from 'scenes/surveys/hooks/useSurveyLinkedInsights'
import { getBestSurveyOpportunityFunnel } from 'scenes/surveys/utils/opportunityDetection'
import { urls } from 'scenes/urls'

import { getCurrentExporterData, isSharedView } from '~/exporter/exporterViewLogic'
import { DashboardLayoutSize, DashboardPlacement, DashboardType } from '~/types'

import { DashboardGridBackground } from 'products/dashboards/frontend/components/DashboardGridBackground'
import { DashboardInsightTile } from 'products/dashboards/frontend/components/DashboardInsightTile'
import { DashboardTextItem } from 'products/dashboards/frontend/components/DashboardTextItem/DashboardTextItem'
import { getDashboardTileSpacingGap } from 'products/dashboards/frontend/dashboardCustomization'
import { getGroupTitlesByTileId, hasTileDecorations } from 'products/dashboards/frontend/dashboardTileGroups'
import { useDashboardContainerWidth } from 'products/dashboards/frontend/useDashboardContainerWidth'

import { DashboardButtonTileItem } from './items/DashboardButtonTileItem'
import { DashboardErrorTileItem } from './items/DashboardErrorTileItem'

const DRAG_AUTO_SCROLL_THRESHOLD = 100
const DRAG_AUTO_SCROLL_SPEED = 50

const BASE_ROW_HEIGHT = 80
const BASE_MARGIN: [number, number] = [16, 16]
const CONTAINER_PADDING: [number, number] = [0, 0]

interface DashboardItemsProps {
    showCreateAnomalyAlertButton?: boolean
}

type DashboardWidgetItemProps = React.ComponentProps<typeof DashboardWidgetItem>

/**
 * Shallow prop compare, except: `style` by value (react-grid-layout rebuilds it every drag/resize mousemove even
 * for tiles that haven't moved) and `children` ignored (the RGL-injected resize handles, recreated each render
 * with identical content). Lets untouched tiles skip re-rendering during gestures.
 */
function gridTilePropsEqual(prevProps: Record<string, any>, nextProps: Record<string, any>): boolean {
    return [...new Set([...Object.keys(prevProps), ...Object.keys(nextProps)])].every(
        (key) =>
            key === 'children' ||
            (key === 'style'
                ? objectsEqual(prevProps.style, nextProps.style)
                : Object.is(prevProps[key], nextProps[key]))
    )
}

const MemoizedDashboardTextItem = memo(DashboardTextItem, gridTilePropsEqual) as typeof DashboardTextItem
const MemoizedDashboardButtonTileItem = memo(
    DashboardButtonTileItem,
    gridTilePropsEqual
) as typeof DashboardButtonTileItem
const MemoizedDashboardErrorTileItem = memo(DashboardErrorTileItem, gridTilePropsEqual) as typeof DashboardErrorTileItem
const MemoizedDashboardWidgetItem = memo(DashboardWidgetItem, gridTilePropsEqual) as typeof DashboardWidgetItem

export function DashboardItems({ showCreateAnomalyAlertButton }: DashboardItemsProps = {}): JSX.Element {
    const {
        dashboard,
        tiles,
        layouts,
        layoutEditMode,
        placement,
        readOnly,
        isRefreshingQueued,
        isRefreshing,
        highlightedInsightId,
        refreshStatus,
        dashboardStreaming,
        dashboardLoading,
        effectiveEditBarFilters,
        currentDashboardVariables,
        effectiveBreakdownColors,
        dataColorThemeId,
        canEditDashboard,
        widgetResultsByTileId,
        widgetRefreshStatus,
        scrollToBottomSignal,
        sizeKey,
    } = useValues(dashboardLogic)
    const { layoutZoom = 1 } = useValues(dashboardLogic)
    const {
        updateLayouts,
        updateContainerWidth,
        toggleTileDescription,
        removeTile,
        duplicateTile,
        loadDashboard,
        refreshDashboardWidgets,
        scheduleRefreshDashboardWidgets,
        applyWidgetIssueMetadataChange,
        moveToDashboard,
        copyToDashboard,
        setDashboardEditing,
    } = useActions(dashboardLogic)
    const { updateWidgetTile } = useAsyncActions(dashboardLogic)
    const { reportDashboardTileRepositioned } = useActions(eventUsageLogic)
    const { push } = useActions(router)
    const { data: surveyLinkedInsights, loading: surveyLinkedInsightsLoading } = useSurveyLinkedInsights({
        // Dashboard pages hide the survey suggestion in compact headers; notebook embeds also use this component and can show it.
        skip: placement === DashboardPlacement.Dashboard,
    })

    const bestSurveyOpportunityFunnel = surveyLinkedInsightsLoading
        ? null
        : getBestSurveyOpportunityFunnel(tiles || [], surveyLinkedInsights)
    const retryFailedDashboardTile = isSharedView()
        ? undefined
        : () => loadDashboard({ action: DashboardLoadAction.Update })

    const [containerHeight, setContainerHeight] = useState<number | undefined>(undefined)

    // cannot click links when dragging and 250ms after
    const isDragging = useRef(false)
    // While a drag/resize is in progress the grid drives itself from its own internal state and ignores the
    // `layouts` prop, so pushing layout updates to the store mid-gesture only triggers expensive full re-renders
    // (every InsightCard) that make the dragged tile lag the cursor. Stash the latest layout and commit once on stop.
    const dragEndTimeout = useRef<number | null>(null)
    const scrollAnimationRef = useRef<number | null>(null)
    const scrollContainerRef = useRef<HTMLElement | null>(null)
    const scrollContainerRectRef = useRef<DOMRect | null>(null)
    const lastScrollSignalRef = useRef(scrollToBottomSignal)

    useEffect(() => {
        return () => {
            if (scrollAnimationRef.current) {
                cancelAnimationFrame(scrollAnimationRef.current)
            }
            if (dragEndTimeout.current) {
                window.clearTimeout(dragEndTimeout.current)
            }
            scrollContainerRef.current = null
            scrollContainerRectRef.current = null
        }
    }, [])

    // Scroll the dashboard to the bottom when the logic requests it (e.g. after adding tiles).
    // Two animation frames let React commit and react-grid-layout grow the container before we measure.
    useEffect(() => {
        if (scrollToBottomSignal === lastScrollSignalRef.current) {
            return
        }
        lastScrollSignalRef.current = scrollToBottomSignal

        let secondFrame = 0
        const firstFrame = requestAnimationFrame(() => {
            secondFrame = requestAnimationFrame(() => {
                const scrollContainer = document.getElementById('main-content')
                scrollContainer?.scrollTo({ top: scrollContainer.scrollHeight, behavior: 'smooth' })
            })
        })
        return () => {
            cancelAnimationFrame(firstFrame)
            cancelAnimationFrame(secondFrame)
        }
    }, [scrollToBottomSignal])
    const className = clsx({
        'dashboard-view-mode mb-8': !layoutEditMode,
        // In edit mode, dragging is bounded to the grid's own clientHeight, which is exactly the
        // content height — so there's nowhere to drag a tile into to create a new bottom row.
        // box-content + padding-bottom grows clientHeight (padding only counts under content-box,
        // since preflight defaults everything to border-box), opening up draggable space below the
        // last tile that scales with content. A margin wouldn't work — it sits outside clientHeight.
        'dashboard-edit-mode box-content pb-[40vh]': layoutEditMode,
    })

    const { width: gridWidth, containerRef } = useDashboardContainerWidth()
    const { gridCompactor, handleLayoutChange, interactionInProgress, startInteraction, finishInteraction } =
        useDashboardLayoutInteraction({
            layoutEditMode,
            layoutCompaction: dashboard?.customization?.layout_compaction,
            updateLayouts,
        })

    useEffect(() => {
        if (!containerRef.current) {
            return
        }

        const element = containerRef.current
        const observer = new ResizeObserver((entries) => {
            // Skip per-frame height commits during a gesture — they re-render every tile just for GridBackground,
            // lagging the cursor. flushPendingLayouts remeasures on stop.
            if (interactionInProgress.current) {
                return
            }
            for (const entry of entries) {
                if (entry.target === element) {
                    setContainerHeight(entry.contentRect.height)
                }
            }
        })

        // Set initial height
        setContainerHeight(element.clientHeight)
        observer.observe(element)

        return () => {
            observer.disconnect()
        }
    }, [containerRef])
    const isMobileView = !!gridWidth && gridWidth <= BREAKPOINTS['sm']
    const isEditablePlacement =
        !readOnly &&
        [DashboardPlacement.Dashboard, DashboardPlacement.ProjectHomepage, DashboardPlacement.Builtin].includes(
            placement
        )

    const canEnterEditModeFromEdge =
        !!dashboard && canEditDashboard && !layoutEditMode && !isMobileView && isEditablePlacement

    const isLayoutZoomToggled = layoutEditMode && layoutZoom !== 1

    const effectiveZoom = layoutEditMode ? layoutZoom : 1
    const rowHeight = BASE_ROW_HEIGHT * effectiveZoom
    const spacingFactor = effectiveZoom < 1 ? 0.9 : 1
    const gridGap = getDashboardTileSpacingGap(dashboard?.customization?.tile_spacing)
    const margin = useMemo(
        () => BASE_MARGIN.map(() => gridGap * spacingFactor) as [number, number],
        [gridGap, spacingFactor]
    )

    const widgetTilesShown = isWidgetTileVisibleOnPlacement(placement)
    const activeBreakpoint = sizeKey ?? 'sm'
    const groupTitlesByTileId = useMemo(
        () =>
            getGroupTitlesByTileId({
                tiles: tiles || [],
                layout: layouts[activeBreakpoint],
                activeBreakpoint,
                groupTitles: dashboard?.customization?.group_titles,
                compactor: gridCompactor,
                widgetTilesShown,
            }),
        [tiles, layouts, activeBreakpoint, dashboard?.customization?.group_titles, gridCompactor, widgetTilesShown]
    )
    const decorationsByTileId = useMemo(
        () =>
            new Map(
                (tiles ?? []).map((tile) => [
                    tile.id,
                    <TileDecorations key={tile.id} badge={tile.badge} groupTitle={groupTitlesByTileId[tile.id]} />,
                ])
            ),
        [tiles, groupTitlesByTileId]
    )
    const showDecorationSpace = hasTileDecorations({ tiles: tiles || [], groupTitlesByTileId, widgetTilesShown })

    const showResizeHandles = layoutEditMode && !isMobileView && isEditablePlacement && !isLayoutZoomToggled
    const showEditingControls = isEditablePlacement || layoutEditMode
    const showDetailsControls =
        placement !== DashboardPlacement.Export &&
        placement !== DashboardPlacement.Public &&
        !getCurrentExporterData()?.hideExtraDetails

    const dragConfig = useMemo(
        () => ({
            enabled: canEditDashboard && layoutEditMode && !isMobileView,
            handle: '.CardMeta,.DashboardTileCard__body,.WidgetCard__header,.drag-handle',
            cancel: 'a,table,button,input,.Popover',
            bounded: true,
        }),
        [canEditDashboard, layoutEditMode, isMobileView]
    )

    const resizeConfig = useMemo(
        () => ({
            enabled: canEditDashboard && layoutEditMode && !isMobileView && !isLayoutZoomToggled,
            handles: ['s', 'e', 'se', 'w', 'sw'] as const,
        }),
        [canEditDashboard, layoutEditMode, isMobileView, isLayoutZoomToggled]
    )

    useResizeHandleScrollbarPassThrough(layoutEditMode && !isMobileView)

    const canEnterEditModeFromEdgeRef = useRef(canEnterEditModeFromEdge)
    canEnterEditModeFromEdgeRef.current = canEnterEditModeFromEdge
    const onEnterEditModeFromEdge = useCallback(
        (e: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge): void => {
            if (!canEnterEditModeFromEdgeRef.current) {
                return
            }
            setDashboardEditing({ filters: true, layout: true }, DashboardEventSource.CardEdgeHover)
            continueResizeGestureInEditMode(e, edge, e.nativeEvent)
        },
        [setDashboardEditing]
    )

    const onDragHandleMouseDown = useCallback(
        (e: React.MouseEvent): void => {
            if (!canEnterEditModeFromEdgeRef.current) {
                return
            }
            const target = e.target as Element | null
            if (!target || !target.closest('.react-grid-item')) {
                return
            }
            if (
                target.closest(
                    'input,textarea,button,select,a,p,h4,[contenteditable="true"],[role="textbox"],.ProseMirror,.LemonMarkdown'
                )
            ) {
                return
            }
            e.preventDefault()
            e.stopPropagation()
            whenPressBecomesDrag(e, (moveEvent) => {
                if (!canEnterEditModeFromEdgeRef.current) {
                    return
                }
                setDashboardEditing({ filters: true, layout: true }, DashboardEventSource.CardDragHandle)
                continueDragGestureInEditMode(e, moveEvent)
            })
        },
        [setDashboardEditing]
    )

    const requireDashboardId = useCallback(
        (action: string): number => {
            if (!dashboard) {
                throw new Error(`must be on a dashboard to ${action}`)
            }
            return dashboard.id
        },
        [dashboard]
    )

    const onWidgetIssueMetadataChange = useCallback<
        NonNullable<DashboardWidgetItemProps['onApplyWidgetIssueMetadataChange']>
    >(
        (tileId, issueId, delta, context): void => {
            applyWidgetIssueMetadataChange({ tileId, issueId, delta, context })
        },
        [applyWidgetIssueMetadataChange]
    )
    const onWidgetConfigPublished = useCallback((): void => {
        loadDashboard({ action: DashboardLoadAction.Update })
    }, [loadDashboard])

    const tileActionsById = useMemo(
        () =>
            new Map(
                (tiles ?? []).map((tile) => [
                    tile.id,
                    {
                        moveToDashboard: ({ id, name }: Pick<DashboardType, 'id' | 'name'>): void => {
                            moveToDashboard(tile, requireDashboardId('move this tile'), id, name)
                        },
                        copyToDashboard: ({ id, name }: Pick<DashboardType, 'id' | 'name'>): void => {
                            copyToDashboard(tile, requireDashboardId('copy this tile'), id, name)
                        },
                        removeFromDashboard: (): void => removeTile(tile),
                        duplicate: (): void => duplicateTile(tile),
                        edit: (): void => {
                            if (dashboard?.id) {
                                push(urls.dashboardTile(dashboard.id, tile.id))
                            }
                        },
                        refreshWidget: (): void => refreshDashboardWidgets({ tileIds: [tile.id], forceRefresh: true }),
                        updateWidget: async (
                            patch: Parameters<NonNullable<DashboardWidgetItemProps['onUpdateWidgetTile']>>[0]
                        ): Promise<void> => {
                            await updateWidgetTile({ tile, ...patch })
                        },
                        toggleDescription: (): void => toggleTileDescription(tile.id),
                    },
                ])
            ),
        [
            tiles,
            dashboard?.id,
            requireDashboardId,
            moveToDashboard,
            copyToDashboard,
            removeTile,
            duplicateTile,
            push,
            refreshDashboardWidgets,
            updateWidgetTile,
            toggleTileDescription,
        ]
    )

    const flushPendingLayouts = useCallback(() => {
        finishInteraction()
        // Remeasure once the gesture settles, since height updates were suppressed during it.
        requestAnimationFrame(() => {
            if (containerRef.current) {
                setContainerHeight(containerRef.current.clientHeight)
            }
        })
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- ref reads inside requestAnimationFrame aren't valid deps
    }, [finishInteraction])

    const handleWidthChange = useCallback(
        (containerWidth: number, _: unknown, newCols: number) => {
            updateContainerWidth(containerWidth, newCols)
        },
        [updateContainerWidth]
    )

    const handleResizeStart = useCallback(
        (
            layout: Layout,
            _oldItem: LayoutItem | null,
            newItem: LayoutItem | null,
            _placeholder: LayoutItem | null,
            event: Event
        ) => {
            event.preventDefault()
            if (!newItem) {
                return
            }
            startInteraction(layout, newItem, 'resize')
        },
        [startInteraction]
    )

    const handleResizeStop = useCallback(() => {
        flushPendingLayouts()
        if (dashboard?.id) {
            reportDashboardTileRepositioned(dashboard.id, 'resized', effectiveZoom)
        }
    }, [dashboard?.id, reportDashboardTileRepositioned, effectiveZoom, flushPendingLayouts])

    const handleDragStart = useCallback(
        (layout: Layout, _oldItem: LayoutItem | null, newItem: LayoutItem | null) => {
            if (!newItem) {
                return
            }
            startInteraction(layout, newItem, 'drag')
            scrollContainerRef.current = document.getElementById('main-content')
            scrollContainerRectRef.current = scrollContainerRef.current?.getBoundingClientRect() ?? null
        },
        [startInteraction]
    )

    const handleDrag = useCallback(
        (_layout: unknown, _oldItem: unknown, _newItem: unknown, _placeholder: unknown, e: unknown) => {
            isDragging.current = true
            if (dragEndTimeout.current) {
                window.clearTimeout(dragEndTimeout.current)
            }
            if (scrollAnimationRef.current) {
                cancelAnimationFrame(scrollAnimationRef.current)
                scrollAnimationRef.current = null
            }

            const scrollContainer = scrollContainerRef.current
            const containerRect = scrollContainerRectRef.current
            if (!scrollContainer || !containerRect) {
                return
            }

            const mouseY = (e as MouseEvent).clientY

            let scrollSpeed = 0
            if (mouseY < containerRect.top + DRAG_AUTO_SCROLL_THRESHOLD) {
                scrollSpeed = -DRAG_AUTO_SCROLL_SPEED
            } else if (mouseY > containerRect.bottom - DRAG_AUTO_SCROLL_THRESHOLD) {
                scrollSpeed = DRAG_AUTO_SCROLL_SPEED
            }

            if (scrollSpeed !== 0) {
                const scroll = (): void => {
                    const atTop = scrollSpeed < 0 && scrollContainer.scrollTop === 0
                    const atBottom =
                        scrollSpeed > 0 &&
                        scrollContainer.scrollTop + scrollContainer.clientHeight >= scrollContainer.scrollHeight
                    if (atTop || atBottom) {
                        return
                    }
                    scrollContainer.scrollBy(0, scrollSpeed)
                    scrollAnimationRef.current = requestAnimationFrame(scroll)
                }
                scrollAnimationRef.current = requestAnimationFrame(scroll)
            }
        },
        []
    )

    const handleDragStop = useCallback(() => {
        if (scrollAnimationRef.current) {
            cancelAnimationFrame(scrollAnimationRef.current)
            scrollAnimationRef.current = null
        }
        scrollContainerRef.current = null
        scrollContainerRectRef.current = null
        if (dragEndTimeout.current) {
            window.clearTimeout(dragEndTimeout.current)
        }
        dragEndTimeout.current = window.setTimeout(() => {
            isDragging.current = false
        }, 250)
        flushPendingLayouts()
        if (dashboard?.id) {
            reportDashboardTileRepositioned(dashboard.id, 'moved', effectiveZoom)
        }
    }, [dashboard?.id, reportDashboardTileRepositioned, effectiveZoom, flushPendingLayouts])

    return (
        <div className="dashboard-items-wrapper" ref={containerRef as RefObject<HTMLDivElement>}>
            {layoutEditMode && isMobileView && (
                <LemonBanner type="warning" className="mb-4">
                    Layout editing is disabled on smaller screens. Please zoom out or use a larger screen to move or
                    resize tiles.
                </LemonBanner>
            )}
            {gridWidth > 0 && (
                <div className={clsx('relative', showDecorationSpace && 'mt-10')}>
                    {layoutEditMode && !isMobileView && (
                        <DashboardGridBackground
                            width={gridWidth}
                            cols={BREAKPOINT_COLUMN_COUNTS.sm}
                            rowHeight={rowHeight}
                            margin={margin}
                            height={containerHeight} // kept in sync via ResizeObserver
                        />
                    )}

                    <ReactGridLayout
                        width={gridWidth}
                        style={{ width: gridWidth }}
                        className={className}
                        dragConfig={dragConfig}
                        resizeConfig={resizeConfig}
                        layouts={layouts as Partial<Record<DashboardLayoutSize, Layout>>}
                        compactor={gridCompactor}
                        rowHeight={rowHeight}
                        margin={margin}
                        containerPadding={CONTAINER_PADDING}
                        onLayoutChange={handleLayoutChange}
                        onWidthChange={handleWidthChange}
                        breakpoints={BREAKPOINTS}
                        cols={BREAKPOINT_COLUMN_COUNTS}
                        onResizeStart={handleResizeStart}
                        onResizeStop={handleResizeStop}
                        onDragStart={handleDragStart}
                        onDrag={handleDrag}
                        onDragStop={handleDragStop}
                    >
                        {tiles?.map((tile) => {
                            const { insight, text, button_tile, widget } = tile
                            const tileActions = tileActionsById.get(tile.id)!
                            const smLayout = layouts['sm']?.find((l) => {
                                return l.i == tile.id.toString()
                            })

                            const decorations = decorationsByTileId.get(tile.id)

                            const commonTileProps = {
                                dashboardId: dashboard?.id,
                                canEditDashboard,
                                showResizeHandles,
                                canEnterEditModeFromEdge,
                                onEnterEditModeFromEdge,
                                onDragHandleMouseDown,
                                showEditingControls,
                                moveToDashboard: tileActions.moveToDashboard,
                                copyToDashboard: tileActions.copyToDashboard,
                                removeFromDashboard: tileActions.removeFromDashboard,
                            }

                            if (tile.error && !insight) {
                                return (
                                    <MemoizedDashboardErrorTileItem
                                        key={tile.id}
                                        tile={tile}
                                        onRetry={retryFailedDashboardTile}
                                        retryLoading={dashboardLoading}
                                        placement={placement}
                                        onRemove={commonTileProps.removeFromDashboard}
                                        showResizeHandles={showResizeHandles}
                                        canEnterEditModeFromEdge={canEnterEditModeFromEdge}
                                        onEnterEditModeFromEdge={onEnterEditModeFromEdge}
                                        onDragHandleMouseDown={onDragHandleMouseDown}
                                        showEditingControls={showEditingControls}
                                    >
                                        {decorations}
                                    </MemoizedDashboardErrorTileItem>
                                )
                            }

                            if (insight) {
                                // Check if this insight has an error from the server
                                const isErrorTile = !!tile.error
                                const queryError = getInsightQueryError(insight)
                                const apiErrored =
                                    isErrorTile || !!queryError || refreshStatus[insight.short_id]?.errored || false
                                const refreshError = refreshStatus[insight.short_id]?.error
                                const apiError = isErrorTile
                                    ? new ApiError(undefined, 500, undefined, {
                                          detail: tile.error!.message,
                                          code: 'dashboard_tile_error',
                                      })
                                    : refreshError || queryError || undefined
                                const loadingQueued = isErrorTile ? false : isRefreshingQueued(insight.short_id)
                                const loading = isErrorTile ? false : isRefreshing(insight.short_id)

                                return (
                                    <DashboardInsightTile
                                        key={tile.id}
                                        tile={tile}
                                        insight={insight}
                                        loadingQueued={loadingQueued}
                                        loading={loading}
                                        apiErrored={apiErrored}
                                        apiError={apiError}
                                        queryId={insight.query_status?.id}
                                        highlighted={highlightedInsightId && insight.short_id === highlightedInsightId}
                                        ribbonColor={tile.color}
                                        showDetailsControls={showDetailsControls}
                                        placement={placement}
                                        loadPriority={smLayout ? smLayout.y * 1000 + smLayout.x : undefined}
                                        filtersOverride={effectiveEditBarFilters}
                                        variablesOverride={currentDashboardVariables}
                                        // :HACKY: The two props below aren't actually used in the component, but are needed to trigger a re-render
                                        breakdownColorOverride={effectiveBreakdownColors}
                                        dataColorThemeId={dataColorThemeId}
                                        surveyOpportunity={tile.id === bestSurveyOpportunityFunnel?.id}
                                        showCreateAnomalyAlertButton={showCreateAnomalyAlertButton}
                                        decorations={decorations}
                                        {...commonTileProps}
                                    />
                                )
                            }

                            if (text) {
                                return (
                                    <MemoizedDashboardTextItem
                                        key={tile.id}
                                        tile={tile}
                                        placement={placement}
                                        dashboardId={dashboard?.id}
                                        onEdit={tileActions.edit}
                                        onMoveToDashboard={commonTileProps.moveToDashboard}
                                        onCopyToDashboard={commonTileProps.copyToDashboard}
                                        onDuplicate={tileActions.duplicate}
                                        onRemove={commonTileProps.removeFromDashboard}
                                        showResizeHandles={commonTileProps.showResizeHandles}
                                        showEditingControls={commonTileProps.showEditingControls}
                                        canEnterEditModeFromEdge={commonTileProps.canEnterEditModeFromEdge}
                                        onEnterEditModeFromEdge={commonTileProps.onEnterEditModeFromEdge}
                                        onDragHandleMouseDown={commonTileProps.onDragHandleMouseDown}
                                    >
                                        {decorations}
                                    </MemoizedDashboardTextItem>
                                )
                            }

                            if (button_tile) {
                                return (
                                    <MemoizedDashboardButtonTileItem
                                        key={tile.id}
                                        tile={tile}
                                        placement={placement}
                                        dashboardId={dashboard?.id}
                                        isDraggingRef={isDragging}
                                        onEdit={tileActions.edit}
                                        onMoveToDashboard={commonTileProps.moveToDashboard}
                                        onDuplicate={tileActions.duplicate}
                                        onRemove={commonTileProps.removeFromDashboard}
                                        showResizeHandles={commonTileProps.showResizeHandles}
                                        showEditingControls={commonTileProps.showEditingControls}
                                        canEnterEditModeFromEdge={commonTileProps.canEnterEditModeFromEdge}
                                        onEnterEditModeFromEdge={commonTileProps.onEnterEditModeFromEdge}
                                        onDragHandleMouseDown={commonTileProps.onDragHandleMouseDown}
                                    >
                                        {decorations}
                                    </MemoizedDashboardButtonTileItem>
                                )
                            }

                            if (widget && widgetTilesShown) {
                                const runResult = widgetResultsByTileId[tile.id]
                                const refreshState = widgetRefreshStatus[tile.id]

                                return (
                                    <MemoizedDashboardWidgetItem
                                        key={tile.id}
                                        tile={tile}
                                        placement={placement}
                                        dashboardId={dashboard?.id}
                                        canEditDashboard={canEditDashboard}
                                        isDashboardEditMode={layoutEditMode}
                                        result={runResult?.result}
                                        error={getDashboardWidgetFetchDisplayError(
                                            runResult?.error ?? refreshState?.error
                                        )}
                                        loading={!!refreshState?.loading}
                                        lastFetchedAt={refreshState?.fetchedAt}
                                        onRefresh={tileActions.refreshWidget}
                                        onRefreshWidgetData={scheduleRefreshDashboardWidgets}
                                        onApplyWidgetIssueMetadataChange={onWidgetIssueMetadataChange}
                                        onUpdateWidgetTile={tileActions.updateWidget}
                                        onConfigPublished={onWidgetConfigPublished}
                                        toggleShowDescription={tileActions.toggleDescription}
                                        onDuplicate={tileActions.duplicate}
                                        onRemove={commonTileProps.removeFromDashboard}
                                        onMoveToDashboard={commonTileProps.moveToDashboard}
                                        onCopyToDashboard={commonTileProps.copyToDashboard}
                                        showResizeHandles={commonTileProps.showResizeHandles}
                                        showEditingControls={commonTileProps.showEditingControls}
                                        canEnterEditModeFromEdge={commonTileProps.canEnterEditModeFromEdge}
                                        onEnterEditModeFromEdge={commonTileProps.onEnterEditModeFromEdge}
                                        onDragHandleMouseDown={commonTileProps.onDragHandleMouseDown}
                                    >
                                        {decorations}
                                    </MemoizedDashboardWidgetItem>
                                )
                            }
                        })}
                    </ReactGridLayout>
                </div>
            )}
            {dashboardStreaming && (
                <div className="mt-4 flex items-center justify-center">
                    <div className="flex items-center gap-2 text-muted">
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600" />
                        <span>Loading tiles...</span>
                    </div>
                </div>
            )}
        </div>
    )
}
