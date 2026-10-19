import { type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Responsive as ReactGridLayout, useContainerWidth } from 'react-grid-layout'
import type { Layout, LayoutItem } from 'react-grid-layout'
import { GridBackground } from 'react-grid-layout/extras'

import type { EditModeEdge } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
// The single-project grid's styles live here, and nothing else on this page loads them.
import 'scenes/dashboard/DashboardItems.scss'
import {
    continueDragGestureInEditMode,
    continueResizeGestureInEditMode,
    whenPressBecomesDrag,
} from 'scenes/dashboard/editLayoutGesture'
import { useDashboardLayoutInteraction } from 'scenes/dashboard/useDashboardLayoutInteraction'

import type { DashboardLayoutSize, InsightColor } from '~/types'

import type { CrossProjectDashboardFilters, CrossProjectTileProject } from './crossProjectDashboardLogic'
import {
    GRID_BREAKPOINTS,
    GRID_COLUMN_COUNTS,
    GRID_MARGIN,
    GRID_ROW_HEIGHT,
    type ResponsiveTileLayouts,
} from './crossProjectLayouts'
import { CrossProjectTile } from './CrossProjectTile'
import type { CrossProjectDashboardTileApi } from './generated/api.schemas'

const DRAG_AUTO_SCROLL_THRESHOLD = 100
const DRAG_AUTO_SCROLL_SPEED = 50
const CONTAINER_PADDING: [number, number] = [0, 0]

// Single-project edit mode's handle, cancel and edge set.
const DRAG_HANDLE = '.CardMeta,.DashboardTileCard__body,.WidgetCard__header,.drag-handle'
const DRAG_CANCEL = 'a,table,button,input,.Popover'
const RESIZE_HANDLES = ['s', 'e', 'se', 'n', 'w', 'nw', 'ne', 'sw'] as const
const NOT_A_DRAG_HANDLE =
    'input,textarea,button,select,a,p,h4,[contenteditable="true"],[role="textbox"],.ProseMirror,.LemonMarkdown'

export interface CrossProjectDashboardGridProps {
    tiles: readonly CrossProjectDashboardTileApi[]
    layouts: Partial<ResponsiveTileLayouts>
    layoutEditMode: boolean
    onEnterLayoutEdit: () => void
    tileProjects: Record<number, CrossProjectTileProject>
    timezonesDiverge: boolean
    missingPropertyKeys: Record<number, string[]>
    dashboardFilters: CrossProjectDashboardFilters
    onLayoutsChange: (layouts: Partial<ResponsiveTileLayouts>) => void
    onSetTileColor: (tileId: string, color: InsightColor | null) => void
    onSetTileOverride: (tile: CrossProjectDashboardTileApi) => void
    onRemoveTile: (tileId: string) => void
}

export function CrossProjectDashboardGrid({
    tiles,
    layouts,
    layoutEditMode,
    onEnterLayoutEdit,
    tileProjects,
    timezonesDiverge,
    missingPropertyKeys,
    dashboardFilters,
    onLayoutsChange,
    onSetTileColor,
    onSetTileOverride,
    onRemoveTile,
}: CrossProjectDashboardGridProps): JSX.Element {
    const { width, containerRef, mounted } = useContainerWidth()
    const [containerHeight, setContainerHeight] = useState(0)
    const [resizingTileId, setResizingTileId] = useState<string | null>(null)
    const scrollContainerRef = useRef<HTMLElement | null>(null)
    const scrollContainerRectRef = useRef<DOMRect | null>(null)
    const scrollAnimationRef = useRef<number | null>(null)

    const updateLayouts = useCallback(
        (next: Partial<Record<DashboardLayoutSize, Layout>>) => onLayoutsChange(next as Partial<ResponsiveTileLayouts>),
        [onLayoutsChange]
    )

    const { gridCompactor, handleLayoutChange, interactionInProgress, startInteraction, finishInteraction } =
        useDashboardLayoutInteraction({ layoutEditMode, updateLayouts })

    // Debounce width changes to the grid. Rapidly crossing the width leaves tiles squashed at one column.
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
            // Height commits during a gesture re-render every tile for the grid background and lag the cursor.
            if (interactionInProgress.current) {
                return
            }
            for (const entry of entries) {
                if (entry.target === element) {
                    setContainerHeight(entry.contentRect.height)
                }
            }
        })
        setContainerHeight(element.clientHeight)
        observer.observe(element)
        return () => observer.disconnect()
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- refs are stable
    }, [mounted, containerRef])

    const isMobileView = !!width && width <= GRID_BREAKPOINTS.sm
    const canEditLayout = layoutEditMode && !isMobileView
    const canEnterEditModeFromEdge = !layoutEditMode && !isMobileView
    const dragConfig = useMemo(
        () => ({ enabled: canEditLayout, handle: DRAG_HANDLE, cancel: DRAG_CANCEL, bounded: true }),
        [canEditLayout]
    )
    const resizeConfig = useMemo(() => ({ enabled: canEditLayout, handles: RESIZE_HANDLES }), [canEditLayout])

    const onEnterEditModeFromEdge = useMemo(
        () =>
            canEnterEditModeFromEdge
                ? (e: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => {
                      whenPressBecomesDrag(e, (moveEvent) => {
                          onEnterLayoutEdit()
                          continueResizeGestureInEditMode(e, edge, moveEvent)
                      })
                  }
                : undefined,
        [canEnterEditModeFromEdge, onEnterLayoutEdit]
    )
    const onDragHandleMouseDown = useMemo(
        () =>
            canEnterEditModeFromEdge
                ? (e: React.MouseEvent) => {
                      const target = e.target as Element | null
                      if (!target?.closest('.react-grid-item') || target.closest(NOT_A_DRAG_HANDLE)) {
                          return
                      }
                      e.preventDefault()
                      e.stopPropagation()
                      whenPressBecomesDrag(e, (moveEvent) => {
                          onEnterLayoutEdit()
                          continueDragGestureInEditMode(e, moveEvent)
                      })
                  }
                : undefined,
        [canEnterEditModeFromEdge, onEnterLayoutEdit]
    )

    const finishGesture = useCallback(() => {
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
            if (newItem) {
                startInteraction(layout, newItem, 'resize')
            }
        },
        [startInteraction]
    )

    const handleResize = useCallback((_layout: unknown, _oldItem: unknown, newItem: LayoutItem | null) => {
        // Setting state to the same id bails out of re-rendering, so this re-renders once per gesture.
        setResizingTileId(newItem?.i ?? null)
    }, [])

    const handleResizeStop = useCallback(() => {
        setResizingTileId(null)
        finishGesture()
    }, [finishGesture])

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
        finishGesture()
    }, [finishGesture])

    return (
        <div
            className="dashboard-items-wrapper"
            ref={containerRef as RefObject<HTMLDivElement>}
            data-attr="cross-project-dashboard-grid"
        >
            {layoutEditMode && isMobileView && (
                <LemonBanner type="warning" className="mb-4">
                    Layout editing is disabled on smaller screens. Please zoom out or use a larger screen to move or
                    resize tiles.
                </LemonBanner>
            )}
            {mounted && (
                <div className="relative">
                    {canEditLayout && (
                        <GridBackground
                            width={gridWidth}
                            cols={GRID_COLUMN_COUNTS.sm}
                            rowHeight={GRID_ROW_HEIGHT}
                            margin={GRID_MARGIN}
                            containerPadding={CONTAINER_PADDING}
                            rows="auto"
                            height={containerHeight}
                            color="var(--color-bg-surface-secondary)"
                        />
                    )}
                    <ReactGridLayout
                        width={gridWidth}
                        className={
                            layoutEditMode
                                ? // Dragging is bounded to the grid's height, so the padding leaves room to drop a tile in a new row.
                                  'dashboard-edit-mode box-content pb-[40vh]'
                                : 'dashboard-view-mode mb-8'
                        }
                        dragConfig={dragConfig}
                        resizeConfig={resizeConfig}
                        layouts={layouts as Partial<Record<DashboardLayoutSize, Layout>>}
                        compactor={gridCompactor}
                        rowHeight={GRID_ROW_HEIGHT}
                        margin={GRID_MARGIN}
                        containerPadding={CONTAINER_PADDING}
                        onLayoutChange={handleLayoutChange}
                        breakpoints={GRID_BREAKPOINTS}
                        cols={GRID_COLUMN_COUNTS}
                        onResizeStart={handleResizeStart}
                        onResize={handleResize}
                        onResizeStop={handleResizeStop}
                        onDragStart={handleDragStart}
                        onDrag={handleDrag}
                        onDragStop={handleDragStop}
                    >
                        {tiles.map((tile) => (
                            <CrossProjectTile
                                key={tile.id}
                                tile={tile}
                                projectName={tileProjects[tile.project_id]?.name}
                                projectTimezone={tileProjects[tile.project_id]?.timezone}
                                showTimezone={timezonesDiverge}
                                missingPropertyKeys={missingPropertyKeys[tile.project_id]}
                                dashboardFilters={dashboardFilters}
                                isResizing={resizingTileId === tile.id}
                                showResizeHandles={canEditLayout}
                                canEnterEditModeFromEdge={canEnterEditModeFromEdge}
                                onEnterEditModeFromEdge={onEnterEditModeFromEdge}
                                onDragHandleMouseDown={onDragHandleMouseDown}
                                onSetColor={(color) => onSetTileColor(tile.id, color)}
                                onSetOverride={() => onSetTileOverride(tile)}
                                onRemove={() => onRemoveTile(tile.id)}
                            />
                        ))}
                    </ReactGridLayout>
                </div>
            )}
        </div>
    )
}
