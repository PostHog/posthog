import './DashboardItems.scss'

import clsx from 'clsx'
import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'
import { RefObject, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Layout, Responsive as ReactGridLayout, useContainerWidth } from 'react-grid-layout'
import { GridBackground, fastVerticalCompactor } from 'react-grid-layout/extras'
import { z } from 'zod'

import { DashboardWidgetItem } from '@posthog/products-dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem'
import { getDashboardWidgetFetchDisplayError } from '@posthog/products-dashboards/frontend/widgets/constants'

import { ApiError } from 'lib/api'
import { InsightCard } from 'lib/components/Cards/InsightCard'
import { EditModeEdge, useResizeHandleScrollbarPassThrough } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { localStorageSlot } from 'lib/utils/localStorageSlot'
import { objectsEqual } from 'lib/utils/objects'
import { addInsightToDashboardLogic } from 'scenes/dashboard/addInsightToDashboardModalLogic'
import { getAddTileMenuItems } from 'scenes/dashboard/DashboardHeaderActions'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import {
    BREAKPOINTS,
    BREAKPOINT_COLUMN_COUNTS,
    getInsightQueryError,
    isWidgetTileVisibleOnPlacement,
} from 'scenes/dashboard/dashboardUtils'
import { continueDragGestureInEditMode, continueResizeGestureInEditMode } from 'scenes/dashboard/editLayoutGesture'
import { InsertTileOverlay } from 'scenes/dashboard/InsertTileOverlay'
import { useSurveyLinkedInsights } from 'scenes/surveys/hooks/useSurveyLinkedInsights'
import { getBestSurveyOpportunityFunnel } from 'scenes/surveys/utils/opportunityDetection'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { insightsModel } from '~/models/insightsModel'
import { DashboardLayoutSize, DashboardMode, DashboardPlacement, DashboardType } from '~/types'

import { DashboardButtonTileItem } from './items/DashboardButtonTileItem'
import { DashboardErrorTileItem } from './items/DashboardErrorTileItem'
import { DashboardGroupItem } from './items/DashboardGroupItem'
import { DashboardTextItem } from './items/DashboardTextItem'
import { collapseDashboardGroupLayouts } from './tileLayouts'

const DRAG_AUTO_SCROLL_THRESHOLD = 100
const DRAG_AUTO_SCROLL_SPEED = 50

const BASE_ROW_HEIGHT = 80
const BASE_MARGIN: [number, number] = [16, 16]
const CONTAINER_PADDING: [number, number] = [0, 0]
const GROUP_FOOTER_PREFIX = 'group-end-'
const collapsedGroupsSchema = z.array(z.string())

/** Strip the synthetic full-width group footer rows before persisting layouts. */
function stripGroupFooterLayouts(
    layouts: Partial<Record<DashboardLayoutSize, Layout>>
): Partial<Record<DashboardLayoutSize, Layout>> {
    const result: Partial<Record<DashboardLayoutSize, Layout>> = {}
    for (const [breakpoint, source] of Object.entries(layouts) as [DashboardLayoutSize, Layout][]) {
        result[breakpoint] = source?.filter((layout) => !layout.i.startsWith(GROUP_FOOTER_PREFIX))
    }
    return result
}

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
        effectiveBreakdownColors,
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
        moveDashboardTileToGroup,
        updateDashboardGroupLayout,
        deleteDashboardGroup,
    } = useActions(dashboardLogic)
    const [collapsedGroupIds, setCollapsedGroupIds] = useState<Set<string>>(() => new Set())
    const [groupLayoutTransitioning, setGroupLayoutTransitioning] = useState(false)
    const [interactionLayouts, setInteractionLayouts] = useState<Partial<Record<DashboardLayoutSize, Layout>> | null>(
        null
    )
    const [pendingGroupDrop, setPendingGroupDrop] = useState<{
        tileId: number
        groupId: string | null
        layout: Layout[number]
    } | null>(null)

    useEffect(() => {
        if (!dashboard?.id || placement === DashboardPlacement.Export) {
            setCollapsedGroupIds(new Set())
            return
        }
        const stored = localStorageSlot(`dashboard-groups-collapsed-v1-${dashboard.id}`, collapsedGroupsSchema).get()
        setCollapsedGroupIds(new Set(stored ?? []))
    }, [dashboard?.id, placement])

    const toggleGroupCollapsed = useCallback(
        (groupId: string) => {
            if (!dashboard?.id || placement === DashboardPlacement.Export) {
                return
            }
            setCollapsedGroupIds((current) => {
                const next = new Set(current)
                if (next.has(groupId)) {
                    next.delete(groupId)
                } else {
                    next.add(groupId)
                }
                localStorageSlot(`dashboard-groups-collapsed-v1-${dashboard.id}`, collapsedGroupsSchema).set([...next])
                return next
            })
            setGroupLayoutTransitioning(true)
            if (groupLayoutTransitionTimeout.current) {
                window.clearTimeout(groupLayoutTransitionTimeout.current)
            }
            groupLayoutTransitionTimeout.current = window.setTimeout(() => setGroupLayoutTransitioning(false), 240)
        },
        [dashboard?.id, placement]
    )

    const effectiveCollapsedGroupIds = collapsedGroupIds
    const displayLayouts = useMemo(() => {
        const activeLayouts = interactionLayouts ?? layouts
        let collapsed: Partial<Record<DashboardLayoutSize, Layout>>
        if (!pendingGroupDrop) {
            collapsed = collapseDashboardGroupLayouts(
                activeLayouts,
                dashboard?.groups ?? [],
                effectiveCollapsedGroupIds
            )
        } else {
            const sm = activeLayouts.sm?.map((layout) =>
                layout.i === String(pendingGroupDrop.tileId) ? pendingGroupDrop.layout : layout
            )
            collapsed = collapseDashboardGroupLayouts(
                { ...activeLayouts, sm },
                dashboard?.groups ?? [],
                effectiveCollapsedGroupIds
            )
        }
        // Pre-compact with the same algorithm the grid uses internally, so the section bands and footer rows
        // computed from these layouts line up with where the grid actually renders each tile.
        const compacted: Partial<Record<DashboardLayoutSize, Layout>> = {}
        for (const [breakpoint, source] of Object.entries(collapsed) as [DashboardLayoutSize, Layout][]) {
            compacted[breakpoint] = fastVerticalCompactor.compact(
                source ?? [],
                BREAKPOINT_COLUMN_COUNTS[breakpoint] ?? BREAKPOINT_COLUMN_COUNTS.sm
            )
        }
        if (!layoutEditMode || !dashboard?.groups?.length) {
            return compacted
        }
        // In edit mode each expanded group gets a full-width static footer row. It blocks grid compaction from
        // pulling tiles dropped below a group up into the group's rows, and doubles as drop space at the group's end.
        const withFooters: Partial<Record<DashboardLayoutSize, Layout>> = {}
        for (const [breakpoint, source] of Object.entries(compacted) as [DashboardLayoutSize, Layout][]) {
            const items = [...(source ?? [])]
            for (const group of dashboard.groups) {
                if (effectiveCollapsedGroupIds.has(group.id)) {
                    continue
                }
                const header = items.find((layout) => layout.i === String(group.tile_id))
                if (!header) {
                    continue
                }
                const memberTileIds = new Set(group.member_tile_ids.map(String))
                let bottom = header.y + header.h
                for (const layout of items) {
                    if (memberTileIds.has(layout.i)) {
                        bottom = Math.max(bottom, layout.y + layout.h)
                    }
                }
                items.push({
                    i: `${GROUP_FOOTER_PREFIX}${group.id}`,
                    x: 0,
                    y: bottom,
                    w: BREAKPOINT_COLUMN_COUNTS[breakpoint] ?? BREAKPOINT_COLUMN_COUNTS.sm,
                    h: 1,
                    static: true,
                })
            }
            withFooters[breakpoint] = items
        }
        return withFooters
    }, [interactionLayouts, layouts, dashboard?.groups, effectiveCollapsedGroupIds, pendingGroupDrop, layoutEditMode])
    const visibleTiles = useMemo(
        () => tiles.filter((tile) => !tile.parent_group_id || !effectiveCollapsedGroupIds.has(tile.parent_group_id)),
        [tiles, effectiveCollapsedGroupIds]
    )
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { updateWidgetTile, renameDashboardGroup } = useAsyncActions(dashboardLogic)
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
    const pendingInteractionLayouts = useRef<Partial<Record<DashboardLayoutSize, Layout>> | null>(null)
    const interactionLayoutFrame = useRef<number | null>(null)
    const dragEndTimeout = useRef<number | null>(null)
    const dragTargetGroupId = useRef<string | null | undefined>(undefined)
    const groupSectionElements = useRef<Array<{ id: string; element: HTMLElement; collapsed: boolean }>>([])
    const groupHeaderTileIds = useRef<Set<string>>(new Set())
    const groupLayoutTransitionTimeout = useRef<number | null>(null)
    const pendingGroupDropTimeout = useRef<number | null>(null)
    const scrollAnimationRef = useRef<number | null>(null)
    const scrollContainerRef = useRef<HTMLElement | null>(null)
    const scrollContainerRectRef = useRef<DOMRect | null>(null)
    const lastScrollSignalRef = useRef(scrollToBottomSignal)

    const queueInteractionLayouts = useCallback((nextLayouts: Partial<Record<DashboardLayoutSize, Layout>>) => {
        pendingInteractionLayouts.current = nextLayouts
        if (interactionLayoutFrame.current === null) {
            interactionLayoutFrame.current = requestAnimationFrame(() => {
                setInteractionLayouts(pendingInteractionLayouts.current)
                interactionLayoutFrame.current = null
            })
        }
    }, [])

    useEffect(() => {
        return () => {
            if (scrollAnimationRef.current) {
                cancelAnimationFrame(scrollAnimationRef.current)
            }
            if (dragEndTimeout.current) {
                window.clearTimeout(dragEndTimeout.current)
            }
            if (groupLayoutTransitionTimeout.current) {
                window.clearTimeout(groupLayoutTransitionTimeout.current)
            }
            if (interactionLayoutFrame.current) {
                cancelAnimationFrame(interactionLayoutFrame.current)
            }
            if (pendingGroupDropTimeout.current) {
                window.clearTimeout(pendingGroupDropTimeout.current)
            }
            scrollContainerRef.current = null
            scrollContainerRectRef.current = null
        }
    }, [])

    useEffect(() => {
        if (!pendingGroupDrop) {
            return
        }
        const tile = tiles.find((candidate) => candidate.id === pendingGroupDrop.tileId)
        const tileLayout = layouts.sm?.find((layout) => layout.i === String(pendingGroupDrop.tileId))
        const layoutMatches =
            tileLayout?.x === pendingGroupDrop.layout.x &&
            tileLayout.y === pendingGroupDrop.layout.y &&
            tileLayout.w === pendingGroupDrop.layout.w &&
            tileLayout.h === pendingGroupDrop.layout.h
        if ((tile?.parent_group_id ?? null) === pendingGroupDrop.groupId && layoutMatches) {
            setPendingGroupDrop(null)
            if (pendingGroupDropTimeout.current) {
                window.clearTimeout(pendingGroupDropTimeout.current)
                pendingGroupDropTimeout.current = null
            }
        }
    }, [layouts.sm, pendingGroupDrop, tiles])

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
        'dashboard-group-transition': groupLayoutTransitioning,
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
    const groupSections = useMemo(() => {
        const smLayouts = displayLayouts.sm ?? []
        const groupLayouts = (dashboard?.groups ?? [])
            .flatMap((group) => {
                const layout = smLayouts.find((candidate) => String(group.tile_id) === candidate.i)
                return layout ? [{ group, layout }] : []
            })
            .sort((a, b) => a.layout.y - b.layout.y)

        return groupLayouts.map(({ group, layout }) => {
            const collapsed = effectiveCollapsedGroupIds.has(group.id)
            const sectionTop = layout.y
            let sectionBottom = layout.y + layout.h

            if (!collapsed) {
                const memberTileIds = new Set(group.member_tile_ids.map(String))
                const memberLayouts = smLayouts.filter((candidate) => memberTileIds.has(candidate.i))
                sectionBottom = memberLayouts.reduce(
                    (bottom, candidate) => Math.max(bottom, candidate.y + candidate.h),
                    sectionBottom
                )
                if (layoutEditMode) {
                    // Cover the synthetic footer row so the band reads as drop space at the group's end.
                    sectionBottom += 1
                }
            }

            const rowSpan = Math.max(1, sectionBottom - sectionTop)
            return {
                id: group.id,
                collapsed,
                startY: sectionTop,
                endY: sectionBottom,
                top: sectionTop * (rowHeight + margin[1]),
                height: rowSpan * rowHeight + (rowSpan - 1) * margin[1],
            }
        })
    }, [dashboard?.groups, displayLayouts.sm, effectiveCollapsedGroupIds, margin, rowHeight, layoutEditMode])

    const getInsertMenuItems = useCallback(
        (targetX: number, targetY: number, targetW?: number): LemonMenuItem[] =>
            dashboard
                ? getAddTileMenuItems({
                      dashboardId: dashboard.id,
                      dashboardWidgetsEnabled,
                      onAddInsight: showAddInsightToDashboardModal,
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
            cancel: 'a,table,button:not(.drag-handle),input,.Popover',
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

    useResizeHandleScrollbarPassThrough(layoutEditMode && !isMobileView)

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
                queueInteractionLayouts(newLayouts)
                return
            }
            updateLayouts(stripGroupFooterLayouts(newLayouts))
        },
        [layoutEditMode, queueInteractionLayouts, updateLayouts]
    )

    const flushPendingLayouts = useCallback(() => {
        interactionInProgress.current = false
        if (interactionLayoutFrame.current) {
            cancelAnimationFrame(interactionLayoutFrame.current)
            interactionLayoutFrame.current = null
        }
        pendingInteractionLayouts.current = null
        setInteractionLayouts(null)
        if (pendingLayouts.current) {
            updateLayouts(stripGroupFooterLayouts(pendingLayouts.current))
            pendingLayouts.current = null
        }
        // Remeasure once the gesture settles, since height updates were suppressed during it.
        requestAnimationFrame(() => {
            if (containerRef.current) {
                setContainerHeight(containerRef.current.clientHeight)
            }
        })
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- ref reads inside requestAnimationFrame aren't valid deps
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

    const handleResize = useCallback(
        (liveLayout: Layout, _oldItem: Layout[number] | null, newItem: Layout[number] | null) => {
            if (!newItem) {
                return
            }
            // Setting state to the same id bails out of re-rendering, so this only re-renders once per gesture.
            setResizingTileId(newItem.i)
            queueInteractionLayouts({ ...layouts, sm: liveLayout })
        },
        [layouts, queueInteractionLayouts]
    )

    const handleResizeStop = useCallback(() => {
        setResizingTileId(null)
        flushPendingLayouts()
        if (dashboard?.id) {
            reportDashboardTileRepositioned(dashboard.id, 'resized', effectiveZoom)
        }
    }, [dashboard?.id, reportDashboardTileRepositioned, effectiveZoom, flushPendingLayouts])

    const handleDragStart = useCallback(() => {
        interactionInProgress.current = true
        dragTargetGroupId.current = undefined
        groupHeaderTileIds.current = new Set((dashboard?.groups ?? []).map((group) => String(group.tile_id)))
        groupSectionElements.current = Array.from(
            document.querySelectorAll<HTMLElement>('[data-attr="dashboard-group-section"][data-group-id]')
        ).flatMap((element) => {
            const id = element.getAttribute('data-group-id')
            return id ? [{ id, element, collapsed: element.getAttribute('data-collapsed') === 'true' }] : []
        })
        scrollContainerRef.current = document.getElementById('main-content')
        scrollContainerRectRef.current = scrollContainerRef.current?.getBoundingClientRect() ?? null
    }, [dashboard?.groups])

    const handleDrag = useCallback(
        (_layout: unknown, _oldItem: unknown, newItem: unknown, _placeholder: unknown, e: unknown) => {
            isDragging.current = true
            const mouseY = (e as MouseEvent).clientY
            const draggedTileId = (newItem as { i?: string } | null)?.i
            const draggingGroupHeader = !!draggedTileId && groupHeaderTileIds.current.has(draggedTileId)
            let destinationId: string | null = null
            if (!draggingGroupHeader) {
                for (const { id, element } of groupSectionElements.current) {
                    const rect = element.getBoundingClientRect()
                    if (mouseY >= rect.top && mouseY <= rect.bottom) {
                        destinationId = id
                        break
                    }
                }
            }
            dragTargetGroupId.current = destinationId
            for (const { id, element } of groupSectionElements.current) {
                element.classList.toggle(
                    'DashboardGroupSection--drop-target',
                    !draggingGroupHeader && id === destinationId
                )
            }
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

    const handleDragStop = useCallback(
        (
            _layout: unknown,
            _oldItem: unknown,
            newItem: { i: string; x: number; y: number; w: number; h: number } | null
        ) => {
            if (!newItem) {
                return
            }
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
            const pointerDestinationGroupId = dragTargetGroupId.current
            dragTargetGroupId.current = undefined
            for (const { element } of groupSectionElements.current) {
                element.classList.remove('DashboardGroupSection--drop-target')
            }
            groupSectionElements.current = []
            const droppedLayouts = pendingLayouts.current ?? displayLayouts
            flushPendingLayouts()
            const group = dashboard?.groups?.find((candidate) => String(candidate.tile_id) === newItem.i)
            if (group) {
                updateDashboardGroupLayout({
                    groupId: group.id,
                    layouts: { sm: { x: 0, y: newItem.y, w: BREAKPOINT_COLUMN_COUNTS.sm, h: 1 } },
                })
            } else {
                const tile = tiles.find((candidate) => String(candidate.id) === newItem.i)
                if (tile) {
                    const orderedGroups = (dashboard?.groups ?? [])
                        .flatMap((candidate) => {
                            const layout = droppedLayouts.sm?.find((layout) => layout.i === String(candidate.tile_id))
                            return layout ? [{ group: candidate, layout }] : []
                        })
                        .sort((a, b) => a.layout.y - b.layout.y)
                    const destination = orderedGroups.filter((candidate) => candidate.layout.y < newItem.y).at(-1)
                    const section = groupSections.find(
                        (candidate) =>
                            !candidate.collapsed && newItem.y >= candidate.startY && newItem.y < candidate.endY
                    )
                    let destinationGroupId = section?.id ?? destination?.group.id ?? null
                    if (pointerDestinationGroupId !== undefined) {
                        destinationGroupId = pointerDestinationGroupId
                    }
                    if ((tile.parent_group_id ?? null) !== destinationGroupId) {
                        const droppedTileLayout = {
                            ...newItem,
                            i: String(tile.id),
                        }
                        setPendingGroupDrop({ tileId: tile.id, groupId: destinationGroupId, layout: droppedTileLayout })
                        if (pendingGroupDropTimeout.current) {
                            window.clearTimeout(pendingGroupDropTimeout.current)
                        }
                        pendingGroupDropTimeout.current = window.setTimeout(() => setPendingGroupDrop(null), 5000)
                        moveDashboardTileToGroup({
                            tileId: tile.id,
                            groupId: destinationGroupId,
                            layouts: { sm: { x: newItem.x, y: newItem.y, w: newItem.w, h: newItem.h } },
                        })
                    }
                }
            }
            if (dashboard?.id) {
                reportDashboardTileRepositioned(dashboard.id, 'moved', effectiveZoom)
            }
        },
        [
            dashboard?.id,
            dashboard?.groups,
            displayLayouts,
            groupSections,
            reportDashboardTileRepositioned,
            effectiveZoom,
            flushPendingLayouts,
            moveDashboardTileToGroup,
            updateDashboardGroupLayout,
            tiles,
        ]
    )

    return (
        <div className="dashboard-items-wrapper" ref={containerRef as RefObject<HTMLDivElement>}>
            {layoutEditMode && isMobileView && (
                <LemonBanner type="warning" className="mb-4">
                    Layout editing is disabled on smaller screens. Please zoom out or use a larger screen to move or
                    resize tiles.
                </LemonBanner>
            )}
            {mounted && (
                <div className={clsx('relative', layoutEditMode && 'dashboard-layout-editing')}>
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
                    {groupSections.map((section) => (
                        <div
                            key={section.id}
                            data-attr="dashboard-group-section"
                            data-group-id={section.id}
                            data-collapsed={section.collapsed}
                            className={clsx(
                                'DashboardGroupSection',
                                groupLayoutTransitioning && 'DashboardGroupSection--transitioning'
                            )}
                            style={{
                                top: section.top - margin[1] / 2,
                                height: section.height + margin[1],
                                left: -margin[0] / 2,
                                right: -margin[0] / 2,
                            }}
                        />
                    ))}
                    <ReactGridLayout
                        width={gridWidth}
                        className={className}
                        dragConfig={dragConfig}
                        resizeConfig={resizeConfig}
                        layouts={displayLayouts as Partial<Record<DashboardLayoutSize, Layout>>}
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
                        {dashboard?.groups?.map((group) => (
                            <DashboardGroupItem
                                key={group.tile_id}
                                group={group}
                                collapsed={effectiveCollapsedGroupIds.has(group.id)}
                                onToggle={() => toggleGroupCollapsed(group.id)}
                                showActions={canEditDashboard && isEditablePlacement}
                                compact={isLayoutZoomToggled}
                                onDragHandleMouseDown={onDragHandleMouseDown}
                                onRename={(name) => renameDashboardGroup(group.id, name)}
                                onDelete={() =>
                                    LemonDialog.open({
                                        title: 'Delete group and its tiles?',
                                        description: `${group.member_tile_ids.length} tiles are in this group. Deleting them is permanent.`,
                                        primaryButton: {
                                            children: 'Delete group and tiles',
                                            status: 'danger',
                                            onClick: () => deleteDashboardGroup(group.id, 'delete_tiles'),
                                        },
                                        secondaryButton: {
                                            children: 'Move tiles to ungrouped',
                                            onClick: () => deleteDashboardGroup(group.id, 'move_to_ungrouped'),
                                        },
                                        tertiaryButton: { children: 'Cancel' },
                                    })
                                }
                            />
                        ))}
                        {layoutEditMode &&
                            dashboard?.groups
                                ?.filter((group) => !effectiveCollapsedGroupIds.has(group.id))
                                .map((group) => (
                                    <div
                                        key={`${GROUP_FOOTER_PREFIX}${group.id}`}
                                        className="DashboardGroupSectionFooter"
                                    />
                                ))}
                        {visibleTiles.map((tile) => {
                            const { insight, text, button_tile, widget } = tile
                            const smLayout = displayLayouts['sm']?.find((l) => {
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

                            if (tile.error && !insight) {
                                return (
                                    <MemoizedDashboardErrorTileItem
                                        key={tile.id}
                                        tile={tile}
                                        onRemove={commonTileProps.removeFromDashboard}
                                        showResizeHandles={showResizeHandles}
                                        canEnterEditModeFromEdge={canEnterEditModeFromEdge}
                                        onEnterEditModeFromEdge={onEnterEditModeFromEdge}
                                        onDragHandleMouseDown={onDragHandleMouseDown}
                                        showEditingControls={showEditingControls}
                                    />
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
                                        breakdownColorOverride={effectiveBreakdownColors}
                                        dataColorThemeId={dataColorThemeId}
                                        surveyOpportunity={tile.id === bestSurveyOpportunityFunnel?.id}
                                        showCreateAnomalyAlertButton={showCreateAnomalyAlertButton}
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
                            layout={displayLayouts['sm']}
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
