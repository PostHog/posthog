import './DashboardItems.scss'

import clsx from 'clsx'
import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'
import { RefObject, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Responsive as ReactGridLayout, useContainerWidth } from 'react-grid-layout'
import type { Layout, LayoutItem } from 'react-grid-layout'
import { GridBackground } from 'react-grid-layout/extras'

import { DashboardWidgetItem } from '@posthog/products-dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem'
import { getDashboardWidgetFetchDisplayError } from '@posthog/products-dashboards/frontend/widgets/constants'

import { ApiError } from 'lib/api'
import { InsightCard } from 'lib/components/Cards/InsightCard'
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
import { insightsModel } from '~/models/insightsModel'
import { DashboardLayoutSize, DashboardPlacement, DashboardTile, DashboardType } from '~/types'

import { DashboardTextItem } from 'products/dashboards/frontend/components/DashboardTextItem/DashboardTextItem'
import { DashboardTileGroup } from 'products/dashboards/frontend/components/DashboardTileGroup/DashboardTileGroup'
import {
    getDashboardGridCompactor,
    getDashboardTileSpacingGap,
} from 'products/dashboards/frontend/dashboardCustomization'
import { getGroupTitlesByTileId, hasTileDecorations } from 'products/dashboards/frontend/dashboardTileGroups'
import {
    type DashboardSection,
    getDashboardSections,
    getLayoutAfterSectionChange,
    getSectionLayouts,
} from 'products/dashboards/frontend/dashboardTileSections'
import { useDashboardGridWidth } from 'products/dashboards/frontend/useDashboardGridWidth'
import { NEW_TILES_SECTION_KEY, useTileGroupDrag } from 'products/dashboards/frontend/useTileGroupDrag'

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

/** A group's padding and side rail make its grid narrower than the dashboard, so each section measures itself. */
function WithMeasuredWidth({
    initialWidth,
    children,
}: {
    initialWidth: number
    children: (width: number) => JSX.Element
}): JSX.Element {
    const { width, containerRef, mounted } = useContainerWidth({ initialWidth })
    const debouncedWidth = useDashboardGridWidth(width)
    return <div ref={containerRef as RefObject<HTMLDivElement>}>{mounted && children(debouncedWidth)}</div>
}

const MemoizedInsightCard = memo(InsightCard, gridTilePropsEqual) as typeof InsightCard
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
        dashboardWidgetsEnabled,
        widgetResultsByTileId,
        widgetRefreshStatus,
        scrollToBottomSignal,
        sizeKey,
        tileGroupSectionsEnabled,
        collapsedTileGroupKeys,
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
        loadDashboard,
        refreshDashboardWidgets,
        scheduleRefreshDashboardWidgets,
        applyWidgetIssueMetadataChange,
        moveToDashboard,
        copyToDashboard,
        setTileOverride,
        setDashboardEditing,
        toggleTileGroup,
        preloadTileGroup,
        moveTileToGroup,
    } = useActions(dashboardLogic)
    const { updateWidgetTile } = useAsyncActions(dashboardLogic)
    const { renameInsight } = useActions(insightsModel)
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
    const refreshDashboardTile = isSharedView() ? undefined : refreshDashboardItem

    // Tile currently being resized. Its viz is unmounted for the duration of the gesture so the chart doesn't
    // redraw on every frame as the tile's dimensions change — the dominant cost that makes resizing feel laggy.
    const [resizingTileId, setResizingTileId] = useState<string | null>(null)
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

    const { width, containerRef, mounted } = useContainerWidth()
    const { gridCompactor, handleLayoutChange, interactionInProgress, startInteraction, finishInteraction } =
        useDashboardLayoutInteraction({
            layoutEditMode,
            layoutCompaction: dashboard?.customization?.layout_compaction,
            updateLayouts,
        })

    // Debounce width changes to the grid. Rapidly crossing the width causes tiles to stay squashed at 1-column
    // width. Debouncing avoids this and reduces unnecessary re-layouts during resize.
    const gridWidth = useDashboardGridWidth(width)

    // Only the whole dashboard's width sets the breakpoint. A group's grid is narrower, and must not switch the
    // dashboard to the one-column layout.
    useEffect(() => {
        if (mounted) {
            updateContainerWidth(gridWidth, BREAKPOINT_COLUMN_COUNTS[gridWidth > BREAKPOINTS.sm ? 'sm' : 'xs'])
        }
    }, [mounted, gridWidth, updateContainerWidth])

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
    const gridGap = getDashboardTileSpacingGap(dashboard?.customization?.tile_spacing)
    const margin = useMemo(
        () => BASE_MARGIN.map(() => gridGap * spacingFactor) as [number, number],
        [gridGap, spacingFactor]
    )

    const widgetTilesShown = dashboardWidgetsEnabled && isWidgetTileVisibleOnPlacement(placement)
    const activeBreakpoint = sizeKey ?? 'sm'
    const groupTitlesByTileId = useMemo(
        () =>
            getGroupTitlesByTileId({
                tiles: tiles || [],
                layout: layouts[activeBreakpoint],
                activeBreakpoint,
                groups: tileGroupSectionsEnabled ? undefined : dashboard?.customization?.groups,
                compactor: gridCompactor,
                widgetTilesShown,
            }),
        [
            tiles,
            layouts,
            activeBreakpoint,
            tileGroupSectionsEnabled,
            dashboard?.customization?.groups,
            gridCompactor,
            widgetTilesShown,
        ]
    )
    const sections = useMemo((): DashboardSection[] => {
        const renderedTiles = (tiles || []).filter((tile) => !tile.widget || widgetTilesShown)
        const groupSections = tileGroupSectionsEnabled
            ? getDashboardSections({
                  tiles: renderedTiles,
                  layout: layouts.sm,
                  groups: dashboard?.customization?.groups,
              })
            : []
        return groupSections.some((section) => section.kind === 'group') ? groupSections : []
    }, [tiles, widgetTilesShown, tileGroupSectionsEnabled, layouts.sm, dashboard?.customization?.groups])
    // `sections` changes on every insight response, but the grids only depend on which tiles each band holds.
    const sectionTileIds = sections.map((section) => section.tiles.map((tile) => tile.id).join(',')).join('|')
    const sectionLayouts = useMemo(
        () => sections.map((section) => getSectionLayouts(layouts, section.tiles)),
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- sectionTileIds stands in for sections
        [sectionTileIds, layouts]
    )
    const showDecorationSpace = hasTileDecorations({ tiles: tiles || [], groupTitlesByTileId, widgetTilesShown })
    const dropCompactor = useMemo(
        () => getDashboardGridCompactor(dashboard?.customization?.layout_compaction),
        [dashboard?.customization?.layout_compaction]
    )
    const { draggingTileId, dropTargetKey, frozenSourceGrid, startTileDrag, trackTileDrag, finishTileDrag } =
        useTileGroupDrag({
            sections,
            sectionLayouts: sectionLayouts.map((sectionLayout) => sectionLayout.sm ?? []),
            layout: layouts.sm ?? [],
            collapsedTileGroupKeys,
            compactor: dropCompactor,
            rowHeight,
            margin,
            toggleTileGroup,
            moveTileToGroup,
            updateLayout: (layout) => updateLayouts({ sm: layout }),
        })

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
            // Tiles in bands must leave their own grid to reach another band.
            bounded: sections.length === 0,
        }),
        [canEditDashboard, layoutEditMode, isMobileView, sections.length]
    )

    const resizeConfig = useMemo(
        () => ({
            enabled: canEditDashboard && layoutEditMode && !isMobileView && !isLayoutZoomToggled,
            handles: ['s', 'e', 'se', 'n', 'w', 'nw', 'ne', 'sw'] as const,
        }),
        [canEditDashboard, layoutEditMode, isMobileView, isLayoutZoomToggled]
    )

    useResizeHandleScrollbarPassThrough(layoutEditMode && !isMobileView)

    const onEnterEditModeFromEdge = useMemo(
        () =>
            canEnterEditModeFromEdge
                ? (e: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => {
                      whenPressBecomesDrag(e, (moveEvent) => {
                          setDashboardEditing({ filters: true, layout: true }, DashboardEventSource.CardEdgeHover)
                          // continue the press into a live resize so the user doesn't have to release and grab again
                          continueResizeGestureInEditMode(e, edge, moveEvent)
                      })
                  }
                : undefined,
        [canEnterEditModeFromEdge, setDashboardEditing]
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
                      whenPressBecomesDrag(e, (moveEvent) => {
                          setDashboardEditing({ filters: true, layout: true }, DashboardEventSource.CardDragHandle)
                          // continue the press into a live drag so the user doesn't have to release and grab again
                          continueDragGestureInEditMode(e, moveEvent)
                      })
                  }
                : undefined,
        [canEnterEditModeFromEdge, setDashboardEditing]
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

    const handleResizeStart = useCallback(
        (layout: Layout, _oldItem: LayoutItem | null, newItem: LayoutItem | null) => {
            if (!newItem) {
                return
            }
            startInteraction(layout, newItem, 'resize')
        },
        [startInteraction]
    )

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

    const handleDragStart = useCallback(
        (
            layout: Layout,
            _oldItem: LayoutItem | null,
            newItem: LayoutItem | null,
            _placeholder: LayoutItem | null,
            _event: Event,
            element: HTMLElement | null
        ) => {
            if (!newItem) {
                return
            }
            startInteraction(layout, newItem, 'drag')
            startTileDrag(newItem, element)
            scrollContainerRef.current = document.getElementById('main-content')
            scrollContainerRectRef.current = scrollContainerRef.current?.getBoundingClientRect() ?? null
        },
        [startInteraction, startTileDrag]
    )

    const handleDrag = useCallback(
        (_layout: unknown, _oldItem: unknown, _newItem: unknown, _placeholder: unknown, e: unknown) => {
            isDragging.current = true
            trackTileDrag(e as Event)
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
                    // The pointer is still, so moved bands under it send no drag event.
                    trackTileDrag(e as Event)
                    scrollAnimationRef.current = requestAnimationFrame(scroll)
                }
                scrollAnimationRef.current = requestAnimationFrame(scroll)
            }
        },
        [trackTileDrag]
    )

    const handleDragStop = useCallback(
        (
            _layout: Layout,
            _oldItem: LayoutItem | null,
            newItem: LayoutItem | null,
            _placeholder: LayoutItem | null,
            event: Event,
            element: HTMLElement | null
        ) => {
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
            finishTileDrag(newItem, element, event)
            if (dashboard?.id) {
                reportDashboardTileRepositioned(dashboard.id, 'moved', effectiveZoom)
            }
        },
        [dashboard?.id, reportDashboardTileRepositioned, effectiveZoom, flushPendingLayouts, finishTileDrag]
    )

    const renderTile = (tile: DashboardTile): JSX.Element | undefined => {
        const { insight, text, button_tile, widget } = tile
        const smLayout = layouts['sm']?.find((l) => {
            return l.i == tile.id.toString()
        })

        const decorations = <TileDecorations badge={tile.badge} groupTitle={groupTitlesByTileId[tile.id]} />

        const commonTileProps = {
            dashboardId: dashboard?.id,
            canEditDashboard,
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
            const apiErrored = isErrorTile || !!queryError || refreshStatus[insight.short_id]?.errored || false
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
                <MemoizedInsightCard
                    key={tile.id}
                    tile={tile}
                    insight={insight}
                    loadingQueued={loadingQueued}
                    loading={loading}
                    apiErrored={apiErrored}
                    apiError={apiError}
                    queryId={insight.query_status?.id}
                    highlighted={highlightedInsightId && insight.short_id === highlightedInsightId}
                    updateColor={(color) => updateTileColor(tile.id, color)}
                    toggleShowDescription={() => toggleTileDescription(tile.id)}
                    ribbonColor={tile.color}
                    refresh={refreshDashboardTile ? () => refreshDashboardTile({ tile }) : undefined}
                    refreshAfterDisplayOptionsChange={
                        refreshDashboardTile
                            ? (updatedInsight) =>
                                  refreshDashboardTile({
                                      tile: { ...tile, insight: updatedInsight },
                                  })
                            : undefined
                    }
                    rename={() => renameInsight(insight)}
                    duplicate={() => duplicateTile(tile)}
                    setOverride={() => setTileOverride(tile)}
                    showDetailsControls={showDetailsControls}
                    placement={placement}
                    loadPriority={smLayout ? smLayout.y * 1000 + smLayout.x : undefined}
                    isResizing={resizingTileId === tile.id.toString()}
                    filtersOverride={effectiveEditBarFilters}
                    variablesOverride={currentDashboardVariables}
                    // :HACKY: The two props below aren't actually used in the component, but are needed to trigger a re-render
                    breakdownColorOverride={effectiveBreakdownColors}
                    dataColorThemeId={dataColorThemeId}
                    surveyOpportunity={tile.id === bestSurveyOpportunityFunnel?.id}
                    showCreateAnomalyAlertButton={showCreateAnomalyAlertButton}
                    {...commonTileProps}
                >
                    {decorations}
                </MemoizedInsightCard>
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
                            push(urls.dashboardTile(dashboard.id, tile.id))
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
                    onEdit={() => {
                        if (dashboard?.id) {
                            push(urls.dashboardTile(dashboard.id, tile.id))
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
                    error={getDashboardWidgetFetchDisplayError(runResult?.error ?? refreshState?.error)}
                    loading={!!refreshState?.loading}
                    lastFetchedAt={refreshState?.fetchedAt}
                    onRefresh={() => refreshDashboardWidgets({ tileIds: [tile.id], forceRefresh: true })}
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
                    onConfigPublished={() => loadDashboard({ action: DashboardLoadAction.Update })}
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
                >
                    {decorations}
                </MemoizedDashboardWidgetItem>
            )
        }
    }

    const renderGrid = (
        gridKey: string,
        width: number,
        gridTiles: DashboardTile[],
        gridLayouts: Partial<Record<DashboardLayoutSize, Layout>>,
        onGridLayoutChange: (layout: Layout, allLayouts: Partial<Record<DashboardLayoutSize, Layout>>) => void,
        gridClassName: string
    ): JSX.Element => (
        <ReactGridLayout
            key={gridKey}
            width={width}
            className={gridClassName}
            dragConfig={dragConfig}
            resizeConfig={resizeConfig}
            // A band is narrower than the dashboard by its padding and rail. The dashboard width picks the
            // breakpoint, so that a band does not switch to one column while the rest of the dashboard has 12.
            breakpoint={gridWidth > BREAKPOINTS.sm ? 'sm' : 'xs'}
            layouts={gridLayouts}
            compactor={gridCompactor}
            rowHeight={rowHeight}
            margin={margin}
            containerPadding={CONTAINER_PADDING}
            onLayoutChange={onGridLayoutChange}
            breakpoints={BREAKPOINTS}
            cols={BREAKPOINT_COLUMN_COUNTS}
            onResizeStart={handleResizeStart}
            onResize={handleResize}
            onResizeStop={handleResizeStop}
            onDragStart={handleDragStart}
            onDrag={handleDrag}
            onDragStop={handleDragStop}
        >
            {gridTiles.map(renderTile)}
        </ReactGridLayout>
    )

    const showUngroupDropZone = layoutEditMode && sections.at(-1)?.kind === 'group'
    const renderSection = (section: DashboardSection, index: number): JSX.Element => {
        const isLastSection = index === sections.length - 1 && !showUngroupDropZone
        const isDraggingOutOfSection =
            !!dropTargetKey && section.tiles.some((tile) => tile.id.toString() === draggingTileId)
        const gridLayouts = sectionLayouts[index]
        const onSectionLayoutChange = (
            layout: Layout,
            allLayouts: Partial<Record<DashboardLayoutSize, Layout>>
        ): void => {
            const dashboardLayout = getLayoutAfterSectionChange(
                sectionLayouts.map((otherLayouts) => otherLayouts.sm ?? []),
                index,
                allLayouts.sm ?? []
            )
            if (dashboardLayout) {
                handleLayoutChange(layout, { sm: dashboardLayout })
            }
        }
        const sectionRows = Math.max(0, ...(gridLayouts.sm ?? []).map((item) => item.y + item.h)) + 1
        const grid = (
            <WithMeasuredWidth initialWidth={gridWidth}>
                {(sectionWidth) => (
                    <div
                        className="relative"
                        data-dashboard-section-grid={section.key}
                        style={frozenSourceGrid?.key === section.key ? { height: frozenSourceGrid.height } : undefined}
                    >
                        {layoutEditMode && !isMobileView && (
                            <GridBackground
                                width={sectionWidth}
                                cols={BREAKPOINT_COLUMN_COUNTS.sm}
                                rowHeight={rowHeight}
                                margin={margin}
                                containerPadding={CONTAINER_PADDING}
                                rows={sectionRows}
                                color="var(--color-bg-surface-secondary)"
                            />
                        )}
                        {renderGrid(
                            // A grid keeps its own layout state and gives a tile it has not seen a 1x1 default,
                            // so a band remounts its grid when a tile moves in or out, but not when tiles reorder.
                            section.tiles
                                .map((tile) => tile.id)
                                .sort((a, b) => a - b)
                                .join('-'),
                            sectionWidth,
                            section.tiles,
                            gridLayouts,
                            onSectionLayoutChange,
                            clsx(
                                layoutEditMode ? 'dashboard-edit-mode box-content' : 'dashboard-view-mode',
                                layoutEditMode && (isLastSection ? 'pb-[40vh]' : 'pb-24'),
                                isDraggingOutOfSection && '[&_.react-grid-placeholder]:hidden'
                            )
                        )}
                    </div>
                )}
            </WithMeasuredWidth>
        )

        return (
            <div
                key={section.key}
                data-dashboard-section={section.key}
                className={clsx('rounded-lg', dropTargetKey === section.key && 'ring-2 ring-accent')}
            >
                {section.kind === 'tiles' ? (
                    grid
                ) : (
                    <DashboardTileGroup
                        group={section.group}
                        tileCount={section.tiles.length}
                        collapsed={collapsedTileGroupKeys.includes(section.groupKey)}
                        onToggle={() => toggleTileGroup(section.groupKey)}
                        onPreload={() => preloadTileGroup(section.groupKey)}
                    >
                        {grid}
                    </DashboardTileGroup>
                )}
            </div>
        )
    }

    return (
        <div className="dashboard-items-wrapper" ref={containerRef as RefObject<HTMLDivElement>}>
            {layoutEditMode && isMobileView && (
                <LemonBanner type="warning" className="mb-4">
                    Layout editing is disabled on smaller screens. Please zoom out or use a larger screen to move or
                    resize tiles.
                </LemonBanner>
            )}
            {mounted && sections.length > 0 && (
                <div className={clsx('flex flex-col gap-4', showDecorationSpace && 'mt-10', !layoutEditMode && 'mb-8')}>
                    {sections.map(renderSection)}
                    {showUngroupDropZone && (
                        <div
                            data-dashboard-section={NEW_TILES_SECTION_KEY}
                            className={clsx(
                                'mb-[40vh] flex h-24 items-center justify-center rounded-lg border border-dashed text-secondary',
                                dropTargetKey === NEW_TILES_SECTION_KEY && 'ring-2 ring-accent'
                            )}
                        >
                            Drag a tile here to take it out of its group
                        </div>
                    )}
                </div>
            )}
            {mounted && sections.length === 0 && (
                <div className={clsx('relative', showDecorationSpace && 'mt-10')}>
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

                    {renderGrid(
                        'dashboard',
                        gridWidth,
                        tiles || [],
                        layouts as Partial<Record<DashboardLayoutSize, Layout>>,
                        handleLayoutChange,
                        className
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
