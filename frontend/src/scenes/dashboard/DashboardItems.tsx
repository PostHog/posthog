import './DashboardItems.scss'

import clsx from 'clsx'
import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'
import { RefObject, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Layout, Responsive as ReactGridLayout, useContainerWidth } from 'react-grid-layout'
import { GridBackground } from 'react-grid-layout/extras'

import { DashboardWidgetItem } from '@posthog/products-dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem'
import { getDashboardWidgetFetchDisplayError } from '@posthog/products-dashboards/frontend/widgets/constants'

import { InsightCard } from 'lib/components/Cards/InsightCard'
import { EditModeEdge } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { objectsEqual } from 'lib/utils/objects'
import { addInsightToDashboardLogic } from 'scenes/dashboard/addInsightToDashboardModalLogic'
import { getAddTileMenuItems } from 'scenes/dashboard/DashboardHeaderActions'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { BREAKPOINTS, BREAKPOINT_COLUMN_COUNTS, isWidgetTileVisibleOnPlacement } from 'scenes/dashboard/dashboardUtils'
import { continueDragGestureInEditMode, continueResizeGestureInEditMode } from 'scenes/dashboard/editLayoutGesture'
import { InsertTileOverlay } from 'scenes/dashboard/InsertTileOverlay'
import { useSurveyLinkedInsights } from 'scenes/surveys/hooks/useSurveyLinkedInsights'
import { getBestSurveyOpportunityFunnel } from 'scenes/surveys/utils/opportunityDetection'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { insightsModel } from '~/models/insightsModel'
import { DashboardLayoutSize, DashboardMode, DashboardPlacement, DashboardType } from '~/types'

import { DashboardButtonTileItem } from './items/DashboardButtonTileItem'
import { DashboardTextItem } from './items/DashboardTextItem'

const DRAG_AUTO_SCROLL_THRESHOLD = 100
const DRAG_AUTO_SCROLL_SPEED = 50

const BASE_ROW_HEIGHT = 80
const BASE_MARGIN: [number, number] = [16, 16]
const CONTAINER_PADDING: [number, number] = [0, 0]

/**
 * react-grid-layout re-renders every grid child on each drag/resize mousemove, cloning it with a freshly built
 * `style` object and freshly created resize-handle `children` even when the tile hasn't moved. Comparing `style`
 * by value and ignoring handle identity lets untouched tiles bail out of re-rendering, which keeps gestures
 * tracking the cursor on dashboards with many tiles.
 */
function gridTilePropsEqual<P extends Record<string, any>>(prevProps: P, nextProps: P): boolean {
    const keys = new Set([...Object.keys(prevProps), ...Object.keys(nextProps)])
    for (const key of keys) {
        if (key === 'children') {
            // Resize handles, recreated each render with identical content. A real handle change (toggling
            // resizability) always comes with a className change, which forces the re-render anyway.
            continue
        }
        if (key === 'style') {
            if (!objectsEqual(prevProps.style, nextProps.style)) {
                return false
            }
            continue
        }
        if (!Object.is(prevProps[key], nextProps[key])) {
            return false
        }
    }
    return true
}

const MemoizedInsightCard = memo(InsightCard, gridTilePropsEqual) as unknown as typeof InsightCard
const MemoizedDashboardTextItem = memo(DashboardTextItem, gridTilePropsEqual) as unknown as typeof DashboardTextItem
const MemoizedDashboardButtonTileItem = memo(
    DashboardButtonTileItem,
    gridTilePropsEqual
) as unknown as typeof DashboardButtonTileItem
const MemoizedDashboardWidgetItem = memo(
    DashboardWidgetItem,
    gridTilePropsEqual
) as unknown as typeof DashboardWidgetItem

export function DashboardItems(): JSX.Element {
    const {
        dashboard,
        tiles,
        layouts,
        dashboardMode,
        layoutEditMode,
        placement,
        isRefreshingQueued,
        isRefreshing,
        highlightedInsightId,
        refreshStatus,
        dashboardStreaming,
        effectiveEditBarFilters,
        effectiveDashboardVariableOverrides,
        temporaryBreakdownColors,
        dataColorThemeId,
        canEditDashboard,
        dashboardWidgetsEnabled,
        inlineTileInsertionEnabled,
        widgetResultsByTileId,
        widgetRefreshStatus,
        scrollToBottomSignal,
    } = useValues(dashboardLogic)
    const { layoutZoom = 1 } = useValues(dashboardLogic)
    const {
        updateLayouts,
        updateContainerWidth,
        updateTileColor,
        toggleTileDescription,
        removeTile,
        duplicateTile,
        refreshDashboardItem,
        refreshDashboardWidgets,
        scheduleRefreshDashboardWidgets,
        applyWidgetIssueMetadataChange,
        moveToDashboard,
        copyToDashboard,
        setTileOverride,
        setDashboardMode,
        setAddWidgetModalOpen,
        setPendingInsertion,
    } = useActions(dashboardLogic)
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { updateWidgetTile } = useAsyncActions(dashboardLogic)
    const { renameInsight } = useActions(insightsModel)
    const { reportDashboardTileRepositioned } = useActions(eventUsageLogic)
    const { push } = useActions(router)
    const { data: surveyLinkedInsights, loading: surveyLinkedInsightsLoading } = useSurveyLinkedInsights({})

    const bestSurveyOpportunityFunnel = surveyLinkedInsightsLoading
        ? null
        : getBestSurveyOpportunityFunnel(tiles || [], surveyLinkedInsights)

    // Tile currently being resized. Its viz is unmounted for the duration of the gesture so the chart doesn't
    // redraw on every frame as the tile's dimensions change — the dominant cost that makes resizing feel laggy.
    const [resizingTileId, setResizingTileId] = useState<string | null>(null)
    const [containerHeight, setContainerHeight] = useState<number | undefined>(undefined)

    // cannot click links when dragging and 250ms after
    const isDragging = useRef(false)
    // While a drag/resize is in progress the grid drives itself from its own internal state and ignores the
    // `layouts` prop, so pushing layout updates to the store mid-gesture only triggers expensive full re-renders
    // (every InsightCard) that make the dragged tile lag the cursor. Stash the latest layout and commit once on stop.
    const interactionInProgress = useRef(false)
    const pendingLayouts = useRef<Partial<Record<DashboardLayoutSize, Layout>> | null>(null)
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

    const { width, containerRef, mounted } = useContainerWidth()

    // Debounce width changes to the grid. Rapidly crossing the width causes tiles to stay squashed at 1-column
    // width. Debouncing avoids this and reduces unnecessary re-layouts during resize.
    const [gridWidth, setGridWidth] = useState(width)
    useEffect(() => {
        const timer = setTimeout(() => setGridWidth(width), 100)
        return () => clearTimeout(timer)
    }, [width])

    useEffect(() => {
        if (!mounted || !containerRef.current) {
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
    }, [mounted, containerRef])
    const isMobileView = !!width && width <= BREAKPOINTS['sm']
    const isEditablePlacement = [
        DashboardPlacement.Dashboard,
        DashboardPlacement.ProjectHomepage,
        DashboardPlacement.Builtin,
    ].includes(placement)

    const canEnterEditModeFromEdge =
        !!dashboard && canEditDashboard && !layoutEditMode && !isMobileView && isEditablePlacement

    const isLayoutZoomToggled = layoutEditMode && layoutZoom !== 1

    const effectiveZoom = layoutEditMode ? layoutZoom : 1
    const rowHeight = BASE_ROW_HEIGHT * effectiveZoom
    const spacingFactor = effectiveZoom < 1 ? 0.9 : 1
    const margin = useMemo(() => BASE_MARGIN.map((m) => m * spacingFactor) as [number, number], [spacingFactor])

    const getInsertMenuItems = useCallback(
        (targetX: number, targetY: number, targetW?: number): LemonMenuItem[] =>
            dashboard
                ? getAddTileMenuItems({
                      dashboardId: dashboard.id,
                      dashboardWidgetsEnabled,
                      showAddInsightToDashboardModal,
                      push,
                      setAddWidgetModalOpen,
                      onBeforeSelect: () => setPendingInsertion({ x: targetX, y: targetY, w: targetW ?? null }),
                  })
                : [],
        [
            dashboard,
            dashboardWidgetsEnabled,
            showAddInsightToDashboardModal,
            push,
            setAddWidgetModalOpen,
            setPendingInsertion,
        ]
    )

    const showResizeHandles = layoutEditMode && !isMobileView && isEditablePlacement && !isLayoutZoomToggled
    const showEditingControls = isEditablePlacement || layoutEditMode
    const showDetailsControls =
        placement !== DashboardPlacement.Export &&
        placement !== DashboardPlacement.Public &&
        !getCurrentExporterData()?.hideExtraDetails

    const dragConfig = useMemo(
        () => ({
            enabled: layoutEditMode && !isMobileView,
            handle: '.CardMeta,.TextCard__body,.ButtonTileCard__body,.WidgetCard__header,.drag-handle',
            cancel: 'a,table,button,input,.Popover',
            bounded: true,
        }),
        [layoutEditMode, isMobileView]
    )

    const resizeConfig = useMemo(
        () => ({
            enabled: layoutEditMode && !isMobileView && !isLayoutZoomToggled,
            handles: ['s', 'e', 'se', 'n', 'w', 'nw', 'ne', 'sw'] as const,
        }),
        [layoutEditMode, isMobileView, isLayoutZoomToggled]
    )

    const onEnterEditModeFromEdge = useMemo(
        () =>
            canEnterEditModeFromEdge
                ? (e: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => {
                      setDashboardMode(DashboardMode.Edit, DashboardEventSource.CardEdgeHover)
                      // continue the press into a live resize so the user doesn't have to release and grab again
                      continueResizeGestureInEditMode(e, edge)
                  }
                : undefined,
        [canEnterEditModeFromEdge, setDashboardMode]
    )

    const onDragHandleMouseDown = useMemo(
        () =>
            canEnterEditModeFromEdge
                ? (e: React.MouseEvent) => {
                      const target = e.target as Element | null
                      if (!target) {
                          return
                      }

                      const gridItem = target.closest('.react-grid-item')
                      if (!gridItem) {
                          return
                      }

                      // Don't trigger when clicking obvious interactive controls or readonly rich text (TipTap/LemonMarkdown).
                      if (
                          target.closest(
                              'input,textarea,button,select,a,p,h4,[contenteditable="true"],[role="textbox"],.ProseMirror,.LemonMarkdown'
                          )
                      ) {
                          return
                      }
                      e.preventDefault()
                      e.stopPropagation()
                      setDashboardMode(DashboardMode.Edit, DashboardEventSource.CardDragHandle)
                      // continue the press into a live drag so the user doesn't have to release and grab again
                      continueDragGestureInEditMode(e)
                  }
                : undefined,
        [canEnterEditModeFromEdge, setDashboardMode]
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

    const handleLayoutChange = useCallback(
        (_: unknown, newLayouts: Partial<Record<DashboardLayoutSize, Layout>>) => {
            if (!layoutEditMode) {
                return
            }
            // Defer commits while dragging/resizing — the final layout is flushed on gesture stop.
            if (interactionInProgress.current) {
                pendingLayouts.current = newLayouts
                return
            }
            updateLayouts(newLayouts)
        },
        [layoutEditMode, updateLayouts]
    )

    const flushPendingLayouts = useCallback(() => {
        interactionInProgress.current = false
        if (pendingLayouts.current) {
            updateLayouts(pendingLayouts.current)
            pendingLayouts.current = null
        }
        // Remeasure once the gesture settles, since height updates were suppressed during it.
        requestAnimationFrame(() => {
            if (containerRef.current) {
                setContainerHeight(containerRef.current.clientHeight)
            }
        })
    }, [updateLayouts])

    const handleWidthChange = useCallback(
        (containerWidth: number, _: unknown, newCols: number) => {
            updateContainerWidth(containerWidth, newCols)
        },
        [updateContainerWidth]
    )

    const handleResizeStart = useCallback(() => {
        interactionInProgress.current = true
    }, [])

    const handleResize = useCallback((_layout: any, _oldItem: any, newItem: any) => {
        // Setting state to the same id bails out of re-rendering, so this only re-renders once per gesture.
        setResizingTileId(newItem.i)
    }, [])

    const handleResizeStop = useCallback(() => {
        setResizingTileId(null)
        flushPendingLayouts()
        if (dashboard?.id) {
            reportDashboardTileRepositioned(dashboard.id, 'resized', effectiveZoom)
        }
    }, [dashboard?.id, reportDashboardTileRepositioned, effectiveZoom, flushPendingLayouts])

    const handleDragStart = useCallback(() => {
        interactionInProgress.current = true
        scrollContainerRef.current = document.getElementById('main-content')
        scrollContainerRectRef.current = scrollContainerRef.current?.getBoundingClientRect() ?? null
    }, [])

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
            {mounted && (
                <div className="relative">
                    {layoutEditMode && !isMobileView && (
                        <GridBackground
                            width={gridWidth}
                            cols={BREAKPOINT_COLUMN_COUNTS.sm}
                            rowHeight={rowHeight}
                            margin={margin}
                            containerPadding={CONTAINER_PADDING}
                            rows="auto"
                            height={containerHeight} // kept in sync via ResizeObserver
                            color="var(--color-bg-surface-secondary)"
                        />
                    )}

                    <ReactGridLayout
                        width={gridWidth}
                        className={className}
                        dragConfig={dragConfig}
                        resizeConfig={resizeConfig}
                        layouts={layouts as Partial<Record<DashboardLayoutSize, Layout>>}
                        rowHeight={rowHeight}
                        margin={margin}
                        containerPadding={CONTAINER_PADDING}
                        onLayoutChange={handleLayoutChange}
                        onWidthChange={handleWidthChange}
                        breakpoints={BREAKPOINTS}
                        cols={BREAKPOINT_COLUMN_COUNTS}
                        onResizeStart={handleResizeStart}
                        onResize={handleResize}
                        onResizeStop={handleResizeStop}
                        onDragStart={handleDragStart}
                        onDrag={handleDrag}
                        onDragStop={handleDragStop}
                    >
                        {tiles?.map((tile) => {
                            const { insight, text, button_tile, widget } = tile
                            const smLayout = layouts['sm']?.find((l) => {
                                return l.i == tile.id.toString()
                            })

                            const commonTileProps = {
                                dashboardId: dashboard?.id,
                                showResizeHandles,
                                canEnterEditModeFromEdge,
                                onEnterEditModeFromEdge,
                                onDragHandleMouseDown,
                                showEditingControls,
                                moveToDashboard: ({ id, name }: Pick<DashboardType, 'id' | 'name'>) => {
                                    moveToDashboard(tile, requireDashboardId('move this tile'), id, name)
                                },
                                copyToDashboard: ({ id, name }: Pick<DashboardType, 'id' | 'name'>) => {
                                    copyToDashboard(tile, requireDashboardId('copy this tile'), id, name)
                                },
                                removeFromDashboard: () => removeTile(tile),
                            }

                            if (insight) {
                                // Check if this insight has an error from the server
                                const isErrorTile = !!tile.error
                                const apiErrored = isErrorTile || refreshStatus[insight.short_id]?.errored || false
                                const apiError = isErrorTile
                                    ? ({ status: 400, detail: `${tile.error!.type}: ${tile.error!.message}` } as any)
                                    : refreshStatus[insight.short_id]?.error
                                const loadingQueued = isErrorTile ? false : isRefreshingQueued(insight.short_id)
                                const loading = isErrorTile ? false : isRefreshing(insight.short_id)

                                return (
                                    <MemoizedInsightCard
                                        key={tile.id}
                                        tile={tile}
                                        insight={insight}
                                        loadingQueued={loadingQueued}
                                        loading={loading}
                                        apiErrored={apiErrored}
                                        apiError={apiError}
                                        highlighted={highlightedInsightId && insight.short_id === highlightedInsightId}
                                        updateColor={(color) => updateTileColor(tile.id, color)}
                                        toggleShowDescription={() => toggleTileDescription(tile.id)}
                                        ribbonColor={tile.color}
                                        refresh={() => refreshDashboardItem({ tile })}
                                        rename={() => renameInsight(insight)}
                                        duplicate={() => duplicateTile(tile)}
                                        setOverride={() => setTileOverride(tile)}
                                        showDetailsControls={showDetailsControls}
                                        placement={placement}
                                        loadPriority={smLayout ? smLayout.y * 1000 + smLayout.x : undefined}
                                        isResizing={resizingTileId === tile.id.toString()}
                                        filtersOverride={effectiveEditBarFilters}
                                        variablesOverride={effectiveDashboardVariableOverrides}
                                        // :HACKY: The two props below aren't actually used in the component, but are needed to trigger a re-render
                                        breakdownColorOverride={temporaryBreakdownColors}
                                        dataColorThemeId={dataColorThemeId}
                                        surveyOpportunity={tile.id === bestSurveyOpportunityFunnel?.id}
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
                                        onEdit={() => {
                                            if (dashboard?.id) {
                                                push(urls.dashboardTextTile(dashboard.id, tile.id))
                                            }
                                        }}
                                        onMoveToDashboard={commonTileProps.moveToDashboard}
                                        onCopyToDashboard={commonTileProps.copyToDashboard}
                                        onDuplicate={() => duplicateTile(tile)}
                                        onRemove={commonTileProps.removeFromDashboard}
                                        showResizeHandles={commonTileProps.showResizeHandles}
                                        showEditingControls={commonTileProps.showEditingControls}
                                        canEnterEditModeFromEdge={commonTileProps.canEnterEditModeFromEdge}
                                        onEnterEditModeFromEdge={commonTileProps.onEnterEditModeFromEdge}
                                        onDragHandleMouseDown={commonTileProps.onDragHandleMouseDown}
                                    />
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
                                        onEdit={() => {
                                            if (dashboard?.id) {
                                                push(urls.dashboardButtonTile(dashboard.id, tile.id))
                                            }
                                        }}
                                        onMoveToDashboard={commonTileProps.moveToDashboard}
                                        onDuplicate={() => duplicateTile(tile)}
                                        onRemove={commonTileProps.removeFromDashboard}
                                        showResizeHandles={commonTileProps.showResizeHandles}
                                        showEditingControls={commonTileProps.showEditingControls}
                                        canEnterEditModeFromEdge={commonTileProps.canEnterEditModeFromEdge}
                                        onEnterEditModeFromEdge={commonTileProps.onEnterEditModeFromEdge}
                                        onDragHandleMouseDown={commonTileProps.onDragHandleMouseDown}
                                    />
                                )
                            }

                            if (widget && dashboardWidgetsEnabled && isWidgetTileVisibleOnPlacement(placement)) {
                                const runResult = widgetResultsByTileId[tile.id]
                                const refreshState = widgetRefreshStatus[tile.id]

                                return (
                                    <MemoizedDashboardWidgetItem
                                        key={tile.id}
                                        tile={tile}
                                        placement={placement}
                                        dashboardId={dashboard?.id}
                                        canEditDashboard={canEditDashboard}
                                        isDashboardEditMode={dashboardMode === DashboardMode.Edit}
                                        result={runResult?.result}
                                        error={getDashboardWidgetFetchDisplayError(
                                            runResult?.error ?? refreshState?.error
                                        )}
                                        loading={!!refreshState?.loading}
                                        lastFetchedAt={refreshState?.fetchedAt}
                                        onRefresh={() =>
                                            refreshDashboardWidgets({ tileIds: [tile.id], forceRefresh: true })
                                        }
                                        onRefreshWidgetData={scheduleRefreshDashboardWidgets}
                                        onApplyWidgetIssueMetadataChange={(tileId, issueId, delta, context) => {
                                            applyWidgetIssueMetadataChange({
                                                tileId,
                                                issueId,
                                                delta,
                                                context,
                                            })
                                        }}
                                        onUpdateWidgetTile={async (patch) => {
                                            await updateWidgetTile({ tile, ...patch })
                                        }}
                                        toggleShowDescription={() => toggleTileDescription(tile.id)}
                                        onDuplicate={() => duplicateTile(tile)}
                                        onRemove={commonTileProps.removeFromDashboard}
                                        onMoveToDashboard={commonTileProps.moveToDashboard}
                                        onCopyToDashboard={commonTileProps.copyToDashboard}
                                        showResizeHandles={commonTileProps.showResizeHandles}
                                        showEditingControls={commonTileProps.showEditingControls}
                                        canEnterEditModeFromEdge={commonTileProps.canEnterEditModeFromEdge}
                                        onEnterEditModeFromEdge={commonTileProps.onEnterEditModeFromEdge}
                                        onDragHandleMouseDown={commonTileProps.onDragHandleMouseDown}
                                    />
                                )
                            }
                        })}
                    </ReactGridLayout>
                    {isEditablePlacement && inlineTileInsertionEnabled && (
                        <InsertTileOverlay
                            layout={layouts['sm']}
                            gridWidth={gridWidth}
                            cols={BREAKPOINT_COLUMN_COUNTS.sm}
                            rowHeight={rowHeight}
                            marginX={margin[0]}
                            marginY={margin[1]}
                            canEditDashboard={canEditDashboard}
                            isMobileView={isMobileView}
                            disabled={resizingTileId !== null}
                            getMenuItems={getInsertMenuItems}
                        />
                    )}
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
