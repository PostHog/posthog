import './DashboardItems.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { RefObject, useEffect, useRef, useState } from 'react'
import { Layout, Responsive as ReactGridLayout, useContainerWidth } from 'react-grid-layout'
import { GridBackground } from 'react-grid-layout/extras'

import { InsightCard } from 'lib/components/Cards/InsightCard'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { BREAKPOINTS, BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'
import { useSurveyLinkedInsights } from 'scenes/surveys/hooks/useSurveyLinkedInsights'
import { getBestSurveyOpportunityFunnel } from 'scenes/surveys/utils/opportunityDetection'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { DashboardLayoutSize, DashboardMode, DashboardPlacement, DashboardType } from '~/types'

import { DashboardTextItem } from './items/DashboardTextItem'

const DRAG_AUTO_SCROLL_THRESHOLD = 100
const DRAG_AUTO_SCROLL_SPEED = 50

const BASE_ROW_HEIGHT = 80
const BASE_MARGIN: [number, number] = [16, 16]

export function DashboardItems(): JSX.Element {
    const {
        dashboard,
        tiles,
        layouts,
        dashboardMode,
        placement,
        isRefreshingQueued,
        isRefreshing,
        highlightedInsightId,
        refreshStatus,
        itemsLoading,
        dashboardStreaming,
        effectiveEditBarFilters,
        effectiveDashboardVariableOverrides,
        temporaryBreakdownColors,
        dataColorThemeId,
        canEditDashboard,
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
        moveToDashboard,
        setTileOverride,
        setDashboardMode,
    } = useActions(dashboardLogic)
    const { renameInsight } = useActions(insightsModel)
    const { reportDashboardTileRepositioned } = useActions(eventUsageLogic)
    const { push } = useActions(router)
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const otherDashboards = nameSortedDashboards.filter((nsdb) => nsdb.id !== dashboard?.id)
    const { data: surveyLinkedInsights, loading: surveyLinkedInsightsLoading } = useSurveyLinkedInsights({})

    const bestSurveyOpportunityFunnel = surveyLinkedInsightsLoading
        ? null
        : getBestSurveyOpportunityFunnel(tiles || [], surveyLinkedInsights)

    const [resizingItem, setResizingItem] = useState<any>(null)
    const [containerHeight, setContainerHeight] = useState<number | undefined>(undefined)

    // cannot click links when dragging and 250ms after
    const isDragging = useRef(false)
    const dragEndTimeout = useRef<number | null>(null)
    const scrollAnimationRef = useRef<number | null>(null)
    const scrollContainerRef = useRef<HTMLElement | null>(null)
    const scrollContainerRectRef = useRef<DOMRect | null>(null)

    useEffect(() => {
        return () => {
            if (scrollAnimationRef.current) {
                cancelAnimationFrame(scrollAnimationRef.current)
            }
        }
    }, [])
    const className = clsx({
        'dashboard-view-mode': dashboardMode !== DashboardMode.Edit,
        'dashboard-edit-mode': dashboardMode === DashboardMode.Edit,
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
    const isMobileView = width && width <= BREAKPOINTS['sm']
    const isEditablePlacement = [
        DashboardPlacement.Dashboard,
        DashboardPlacement.ProjectHomepage,
        DashboardPlacement.Builtin,
    ].includes(placement)

    const canEnterEditModeFromEdge =
        !!dashboard && canEditDashboard && dashboardMode !== DashboardMode.Edit && !isMobileView && isEditablePlacement

    const showDashboardGrid = useFeatureFlag('DASHBOARD_GRID')
    const showLayoutZoom = useFeatureFlag('DASHBOARD_LAYOUT_ZOOM')
    const isLayoutZoomToggled = dashboardMode === DashboardMode.Edit && showLayoutZoom && layoutZoom !== 1

    const effectiveZoom = dashboardMode === DashboardMode.Edit && showLayoutZoom ? layoutZoom : 1
    const rowHeight = BASE_ROW_HEIGHT * effectiveZoom
    const spacingFactor = effectiveZoom < 1 ? 0.9 : 1
    const margin = BASE_MARGIN.map((m) => m * spacingFactor) as [number, number]

    return (
        <div className="dashboard-items-wrapper" ref={containerRef as RefObject<HTMLDivElement>}>
            {dashboardMode === DashboardMode.Edit && isMobileView && (
                <LemonBanner type="warning" className="mb-4">
                    Layout editing is disabled on smaller screens. Please zoom out or use a larger screen to move or
                    resize tiles.
                </LemonBanner>
            )}
            {mounted && (
                <div className="relative">
                    {dashboardMode === DashboardMode.Edit && !isMobileView && showDashboardGrid && (
                        <GridBackground
                            width={gridWidth}
                            cols={BREAKPOINT_COLUMN_COUNTS.sm}
                            rowHeight={rowHeight}
                            margin={margin}
                            containerPadding={[0, 0]}
                            rows="auto"
                            height={containerHeight} // kept in sync via ResizeObserver
                            color="var(--color-bg-surface-secondary)"
                        />
                    )}

                    <ReactGridLayout
                        width={gridWidth}
                        className={className}
                        dragConfig={{
                            enabled: dashboardMode === DashboardMode.Edit && !isMobileView,
                            handle: '.CardMeta,.TextCard__body',
                            cancel: 'a,table,button,input,.Popover',
                            bounded: true,
                        }}
                        resizeConfig={{
                            enabled: dashboardMode === DashboardMode.Edit && !isMobileView && !isLayoutZoomToggled,
                            handles: ['s', 'e', 'se', 'n', 'w', 'nw', 'ne', 'sw'],
                        }}
                        layouts={layouts as Partial<Record<DashboardLayoutSize, Layout>>}
                        rowHeight={rowHeight}
                        margin={margin}
                        containerPadding={[0, 0]}
                        onLayoutChange={(_, newLayouts) => {
                            if (dashboardMode === DashboardMode.Edit) {
                                updateLayouts(newLayouts)
                            }
                        }}
                        onWidthChange={(containerWidth, _, newCols) => {
                            updateContainerWidth(containerWidth, newCols)
                        }}
                        breakpoints={BREAKPOINTS}
                        cols={BREAKPOINT_COLUMN_COUNTS}
                        onResize={(_layout: any, _oldItem: any, newItem: any) => {
                            if (!resizingItem || resizingItem.w !== newItem.w || resizingItem.h !== newItem.h) {
                                setResizingItem(newItem)
                            }
                        }}
                        onResizeStop={() => {
                            setResizingItem(null)
                            if (dashboard?.id) {
                                reportDashboardTileRepositioned(dashboard.id, 'resized', effectiveZoom)
                            }
                        }}
                        onDragStart={() => {
                            scrollContainerRef.current = document.getElementById('main-content')
                            scrollContainerRectRef.current = scrollContainerRef.current?.getBoundingClientRect() ?? null
                        }}
                        onDrag={(_layout, _oldItem, _newItem, _placeholder, e) => {
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
                                        scrollContainer.scrollTop + scrollContainer.clientHeight >=
                                            scrollContainer.scrollHeight
                                    if (atTop || atBottom) {
                                        return
                                    }
                                    scrollContainer.scrollBy(0, scrollSpeed)
                                    scrollAnimationRef.current = requestAnimationFrame(scroll)
                                }
                                scrollAnimationRef.current = requestAnimationFrame(scroll)
                            }
                        }}
                        onDragStop={() => {
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
                            if (dashboard?.id) {
                                reportDashboardTileRepositioned(dashboard.id, 'moved', effectiveZoom)
                            }
                        }}
                    >
                        {tiles?.map((tile) => {
                            const { insight, text } = tile
                            const smLayout = layouts['sm']?.find((l) => {
                                return l.i == tile.id.toString()
                            })

                            const commonTileProps = {
                                dashboardId: dashboard?.id,
                                showResizeHandles:
                                    dashboardMode === DashboardMode.Edit &&
                                    !isMobileView &&
                                    isEditablePlacement &&
                                    !isLayoutZoomToggled,
                                canEnterEditModeFromEdge,
                                onEnterEditModeFromEdge: canEnterEditModeFromEdge
                                    ? () => setDashboardMode(DashboardMode.Edit, DashboardEventSource.CardEdgeHover)
                                    : undefined,
                                onDragHandleMouseDown: canEnterEditModeFromEdge
                                    ? (e: React.MouseEvent) => {
                                          const target = e.target as Element | null
                                          if (!target) {
                                              return
                                          }

                                          const gridItem = target.closest('.react-grid-item')
                                          if (!gridItem) {
                                              return
                                          }

                                          // Don't trigger when clicking obvious interactive controls
                                          if (
                                              target.closest(
                                                  'input,textarea,button,select,a,p,h4,[contenteditable="true"],[role="textbox"]'
                                              )
                                          ) {
                                              return
                                          }
                                          e.preventDefault()
                                          e.stopPropagation()
                                          setDashboardMode(DashboardMode.Edit, DashboardEventSource.CardDragHandle)
                                      }
                                    : undefined,
                                showEditingControls: isEditablePlacement,
                                moveToDashboard: ({ id, name }: Pick<DashboardType, 'id' | 'name'>) => {
                                    if (!dashboard) {
                                        throw new Error('must be on a dashboard to move this tile')
                                    }
                                    moveToDashboard(tile, dashboard.id, id, name)
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
                                    <InsightCard
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
                                        refreshEnabled={!itemsLoading}
                                        rename={() => renameInsight(insight)}
                                        duplicate={() => duplicateTile(tile)}
                                        setOverride={() => setTileOverride(tile)}
                                        showDetailsControls={
                                            placement != DashboardPlacement.Export &&
                                            placement != DashboardPlacement.Public &&
                                            !getCurrentExporterData()?.hideExtraDetails
                                        }
                                        placement={placement}
                                        loadPriority={smLayout ? smLayout.y * 1000 + smLayout.x : undefined}
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
                                    <DashboardTextItem
                                        key={tile.id}
                                        tile={tile}
                                        placement={placement}
                                        otherDashboards={otherDashboards}
                                        isDragging={isDragging.current}
                                        onEdit={() => {
                                            if (dashboard?.id) {
                                                push(urls.dashboardTextTile(dashboard.id, tile.id))
                                            }
                                        }}
                                        onMoveToDashboard={commonTileProps.moveToDashboard}
                                        onDuplicate={() => duplicateTile(tile)}
                                        onRemove={commonTileProps.removeFromDashboard}
                                        showResizeHandles={commonTileProps.showResizeHandles}
                                        canEnterEditModeFromEdge={commonTileProps.canEnterEditModeFromEdge}
                                        onEnterEditModeFromEdge={commonTileProps.onEnterEditModeFromEdge}
                                        onDragHandleMouseDown={commonTileProps.onDragHandleMouseDown}
                                    />
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
