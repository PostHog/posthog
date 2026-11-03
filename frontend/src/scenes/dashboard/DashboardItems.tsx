import './DashboardItems.scss'

import clsx from 'clsx'
import { useActions, useAsyncActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { RefObject, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GridLayout, Responsive as ReactGridLayout } from 'react-grid-layout'
import type { Layout, LayoutItem } from 'react-grid-layout'
import { type PositionStrategy, setTransform } from 'react-grid-layout/core'

import { DashboardWidgetItem } from '@posthog/products-dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem'
import { getDashboardWidgetFetchDisplayError } from '@posthog/products-dashboards/frontend/widgets/constants'

import { ApiError } from 'lib/api'
import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { EditModeEdge, useResizeHandleScrollbarPassThrough } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { TileDecorations } from 'lib/components/TileDecorations/TileDecorations'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { objectsEqual } from 'lib/utils/objects'
import { reportDashboardTileRepositioned } from 'scenes/dashboard/dashboardEvents'
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
import { useDragAutoScroll } from 'scenes/dashboard/useDragAutoScroll'
import { useSurveyLinkedInsights } from 'scenes/surveys/hooks/useSurveyLinkedInsights'
import { getBestSurveyOpportunityFunnel } from 'scenes/surveys/utils/opportunityDetection'
import { urls } from 'scenes/urls'

import { getCurrentExporterData, isSharedView } from '~/exporter/exporterViewLogic'
import { DashboardLayoutSize, DashboardPlacement, DashboardTile, DashboardType } from '~/types'

import { biDashboardCrossFilterLogic } from 'products/business_intelligence/frontend/biDashboardCrossFilterLogic'
import { DashboardGridBackground } from 'products/dashboards/frontend/components/DashboardGridBackground'
import { DashboardInsightTile } from 'products/dashboards/frontend/components/DashboardInsightTile'
import { DashboardTextItem } from 'products/dashboards/frontend/components/DashboardTextItem/DashboardTextItem'
import { DashboardTileGroupTabs } from 'products/dashboards/frontend/components/DashboardTileGroup/DashboardTileGroupTabs'
import { DashboardTileSectionBand } from 'products/dashboards/frontend/components/DashboardTileSectionBand'
import { TileGroupTakeOutDropZone } from 'products/dashboards/frontend/components/TileGroupTakeOutDropZone'
import { getDashboardTileSpacingGap } from 'products/dashboards/frontend/dashboardCustomization'
import { getGroupTitlesByTileId, hasTileDecorations } from 'products/dashboards/frontend/dashboardTileGroups'
import { type DashboardSection, getSectionGroupKey } from 'products/dashboards/frontend/dashboardTileSections'
import { useDashboardContainerWidth } from 'products/dashboards/frontend/useDashboardContainerWidth'
import { TAKE_OUT_DROP_ZONE_KEY, useTileGroupDrag } from 'products/dashboards/frontend/useTileGroupDrag'

import { DashboardButtonTileItem } from './items/DashboardButtonTileItem'
import { DashboardErrorTileItem } from './items/DashboardErrorTileItem'

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

/** Lets a dragged tile leave its band up or down, but not past the sides of its grid. */
function sidewaysBoundedStrategy(gridWidth: number): PositionStrategy {
    return {
        type: 'transform',
        scale: 1,
        calcStyle: (position) =>
            setTransform({ ...position, left: Math.min(Math.max(position.left, 0), gridWidth - position.width) }),
    }
}

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
        copyGroupToDashboardLoading,
        widgetResultsByTileId,
        widgetRefreshStatus,
        scrollToBottomSignal,
        sizeKey,
        tileGroupSectionsEnabled,
        tileGroupSections,
        tileGroupSectionLayouts,
        collapsedTileGroupKeys,
        tileGroupMoveOptions,
        activeTileGroupTab,
        queryLoadQueue,
    } = useValues(dashboardLogic)
    const canCrossFilter = placement === DashboardPlacement.Dashboard && !isSharedView() && !layoutEditMode
    useMountedLogic(
        biDashboardCrossFilterLogic({
            dashboardId: dashboard?.id ?? 0,
            tiles: canCrossFilter ? (tiles ?? []) : [],
            loadQueue: queryLoadQueue,
        })
    )
    const { layoutZoom = 1 } = useValues(dashboardLogic)
    const {
        stageLayouts,
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
        copyGroupToDashboard,
        changeTileGroupDisplay,
        setDashboardEditing,
        toggleTileGroup,
        selectTileGroupTab,
        updateTileGroupSectionLayout,
        moveTileToSection,
    } = useActions(dashboardLogic)
    const { updateWidgetTile } = useAsyncActions(dashboardLogic)
    // dashboard_tiles is empty because this selector covers a whole group, not one tile; the
    // backend still rejects a destination that already has one of the group's tiles.
    const { copyToDestinations } = useValues(
        dashboardWidgetMenusLogic({ instanceKey: 'dashboard-groups', dashboardId: dashboard?.id, dashboard_tiles: [] })
    )
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
    const { startAutoScroll, autoScrollOnDrag, stopAutoScroll } = useDragAutoScroll()
    const lastScrollSignalRef = useRef(scrollToBottomSignal)

    useEffect(() => {
        return () => {
            if (dragEndTimeout.current) {
                window.clearTimeout(dragEndTimeout.current)
            }
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
    const showBands = tileGroupSections.length > 0
    const activeTabIndex = tileGroupSections.findIndex((section) => getSectionGroupKey(section) === activeTileGroupTab)
    const { gridCompactor, handleLayoutChange, interactionInProgress, startInteraction, finishInteraction } =
        useDashboardLayoutInteraction({
            layoutEditMode,
            layoutCompaction: dashboard?.customization?.layout_compaction,
            // Each band grid reports only its own tiles.
            updateLayouts: showBands ? updateTileGroupSectionLayout : stageLayouts,
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

    const onCopyGroupToDashboard = canEditDashboard && isEditablePlacement ? copyGroupToDashboard : undefined
    const onChangeGroupDisplay = canEditDashboard && isEditablePlacement ? changeTileGroupDisplay : undefined

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
    const smLayoutsByTileId = useMemo(() => new Map((layouts['sm'] ?? []).map((l) => [l.i, l])), [layouts])
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
            bounded: !showBands || activeTabIndex >= 0,
        }),
        [canEditDashboard, layoutEditMode, isMobileView, showBands, activeTabIndex]
    )
    const {
        draggingTileId,
        dropTargetKey,
        frozenSourceGrid,
        showTakeOutDropZone,
        startTileDrag,
        trackTileDrag,
        finishTileDrag,
    } = useTileGroupDrag({
        // A tab shows one group, so there is no other band to drop a tile into.
        enabled: dragConfig.enabled && showBands && activeTabIndex < 0,
        sections: tileGroupSections,
        rowHeight,
        margin,
        layout: layouts.sm,
        moveTileToSection: (tileId, sectionKey, cell) => moveTileToSection(tileId, sectionKey, cell, 'drag'),
        restoreLayout: (layout) => stageLayouts({ sm: layout }),
    })
    const boundedStrategy = useMemo(() => sidewaysBoundedStrategy(gridWidth), [gridWidth])

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
                        moveToTileGroup: (sectionKey: string | null): void =>
                            moveTileToSection(tile.id, sectionKey, null, 'menu'),
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
            moveTileToSection,
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

    // Band grids are narrower than the dashboard, so the dashboard width picks one breakpoint for all of them.
    const bandBreakpoint: DashboardLayoutSize = gridWidth > BREAKPOINTS.sm ? 'sm' : 'xs'
    useEffect(() => {
        if (showBands && gridWidth > 0) {
            updateContainerWidth(gridWidth, BREAKPOINT_COLUMN_COUNTS[bandBreakpoint])
        }
    }, [showBands, gridWidth, bandBreakpoint, updateContainerWidth])
    const bandGridConfig = useMemo(
        () => ({
            cols: BREAKPOINT_COLUMN_COUNTS[bandBreakpoint],
            rowHeight,
            margin,
            containerPadding: CONTAINER_PADDING,
        }),
        [bandBreakpoint, rowHeight, margin]
    )
    const handleBandLayoutChange = useCallback(
        (layout: Layout) => handleLayoutChange(layout, { [bandBreakpoint]: layout }),
        [handleLayoutChange, bandBreakpoint]
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
    }, [dashboard?.id, effectiveZoom, flushPendingLayouts])

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
            startAutoScroll()
        },
        [startInteraction, startTileDrag, startAutoScroll]
    )

    const handleDrag = useCallback(
        (_layout: unknown, _oldItem: unknown, _newItem: unknown, _placeholder: unknown, e: Event) => {
            isDragging.current = true
            trackTileDrag(e as Event)
            if (dragEndTimeout.current) {
                window.clearTimeout(dragEndTimeout.current)
            }
            autoScrollOnDrag(e)
        },
        [autoScrollOnDrag, trackTileDrag]
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
            stopAutoScroll()
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
        [dashboard?.id, effectiveZoom, flushPendingLayouts, finishTileDrag, stopAutoScroll]
    )

    const renderTile = (tile: DashboardTile): JSX.Element | undefined => {
        const { insight, text, button_tile, widget } = tile
        const tileActions = tileActionsById.get(tile.id)!
        const smLayout = smLayoutsByTileId.get(tile.id.toString())

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
            tileGroupMoveOptions: showBands ? tileGroupMoveOptions[tile.id] : undefined,
            moveToTileGroup: tileActions.moveToTileGroup,
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
                <DashboardInsightTile
                    key={tile.id}
                    tile={tile}
                    insight={insight}
                    resultMenuEnabled={canCrossFilter}
                    biDashboardTileId={canCrossFilter ? tile.id : undefined}
                    loadingQueued={loadingQueued}
                    loading={loading}
                    // The dashboard load queue owns this tile, so the card must not start its own query.
                    doNotLoad={loading || loadingQueued}
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
                    tileGroupMoveOptions={commonTileProps.tileGroupMoveOptions}
                    onMoveToTileGroup={commonTileProps.moveToTileGroup}
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
                    tileGroupMoveOptions={commonTileProps.tileGroupMoveOptions}
                    onMoveToTileGroup={commonTileProps.moveToTileGroup}
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
                    error={getDashboardWidgetFetchDisplayError(runResult?.error ?? refreshState?.error)}
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
                    tileGroupMoveOptions={commonTileProps.tileGroupMoveOptions}
                    onMoveToTileGroup={commonTileProps.moveToTileGroup}
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

    const gridProps = {
        dragConfig,
        resizeConfig,
        compactor: gridCompactor,
        onResizeStart: handleResizeStart,
        onResizeStop: handleResizeStop,
        onDragStart: handleDragStart,
        onDrag: handleDrag,
        onDragStop: handleDragStop,
    }

    const renderSectionGrid = (section: DashboardSection, index: number): JSX.Element => {
        const sectionLayouts = tileGroupSectionLayouts[index]
        const isLastSection = activeTabIndex >= 0 || (index === tileGroupSections.length - 1 && !showTakeOutDropZone)
        const isDraggingOutOfSection =
            !!dropTargetKey && section.tiles.some((tile) => tile.id.toString() === draggingTileId)
        // One empty row below the tiles gives a dragged tile somewhere to land.
        const sectionRows = Math.max(0, ...(sectionLayouts.sm ?? []).map((item) => item.y + item.h)) + 1
        return (
            <div
                className="relative"
                data-dashboard-section-grid={section.key}
                style={frozenSourceGrid?.key === section.key ? { height: frozenSourceGrid.height } : undefined}
            >
                {layoutEditMode && !isMobileView && (
                    <DashboardGridBackground
                        width={gridWidth}
                        cols={BREAKPOINT_COLUMN_COUNTS.sm}
                        rowHeight={rowHeight}
                        margin={margin}
                        height={sectionRows * (rowHeight + margin[1]) - margin[1]}
                    />
                )}
                {/* Not Responsive: its layout copy and the inner grid's can swap on every render while tiles stream in. */}
                <GridLayout
                    {...gridProps}
                    // The grid takes a new tile's position from `layout`, so a stable key lets tiles stream
                    // into a band without a remount that resets every chart already in it.
                    key={section.key}
                    width={gridWidth}
                    positionStrategy={boundedStrategy}
                    className={clsx(
                        layoutEditMode ? 'dashboard-edit-mode box-content' : 'dashboard-view-mode',
                        layoutEditMode && (isLastSection ? 'pb-[40vh]' : 'pb-24'),
                        isDraggingOutOfSection && '[&_.react-grid-placeholder]:hidden'
                    )}
                    gridConfig={bandGridConfig}
                    layout={sectionLayouts[bandBreakpoint] ?? []}
                    onLayoutChange={handleBandLayoutChange}
                >
                    {section.tiles.map(renderTile)}
                </GridLayout>
            </div>
        )
    }

    const renderSection = (section: DashboardSection, index: number): JSX.Element => (
        <DashboardTileSectionBand
            key={section.key}
            section={section}
            isFirst={index === 0}
            isDropTarget={dropTargetKey === section.key}
            collapsedTileGroupKeys={collapsedTileGroupKeys}
            onToggleTileGroup={toggleTileGroup}
            copyToDestinations={copyToDestinations}
            onCopyGroupToDashboard={onCopyGroupToDashboard}
            copyLoading={copyGroupToDashboardLoading}
            onChangeGroupDisplay={onChangeGroupDisplay}
        >
            {renderSectionGrid(section, index)}
        </DashboardTileSectionBand>
    )

    return (
        <div className="dashboard-items-wrapper" ref={containerRef as RefObject<HTMLDivElement>}>
            {layoutEditMode && isMobileView && (
                <LemonBanner type="warning" className="mb-4">
                    Layout editing is disabled on smaller screens. Please zoom out or use a larger screen to move or
                    resize tiles.
                </LemonBanner>
            )}
            {gridWidth > 0 && activeTabIndex >= 0 && (
                <div className={clsx(showDecorationSpace && 'mt-10', !layoutEditMode && 'mb-8')}>
                    <DashboardTileGroupTabs
                        sections={tileGroupSections}
                        activeSectionKey={tileGroupSections[activeTabIndex].key}
                        onSelect={selectTileGroupTab}
                        copyToDestinations={copyToDestinations}
                        onCopyGroupToDashboard={onCopyGroupToDashboard}
                        copyLoading={copyGroupToDashboardLoading}
                        onChangeGroupDisplay={onChangeGroupDisplay}
                    >
                        {renderSectionGrid(tileGroupSections[activeTabIndex], activeTabIndex)}
                    </DashboardTileGroupTabs>
                </div>
            )}
            {gridWidth > 0 && showBands && activeTabIndex < 0 && (
                <div className={clsx('flex flex-col gap-4', showDecorationSpace && 'mt-10', !layoutEditMode && 'mb-8')}>
                    {tileGroupSections.map(renderSection)}
                    {showTakeOutDropZone && (
                        <TileGroupTakeOutDropZone isDropTarget={dropTargetKey === TAKE_OUT_DROP_ZONE_KEY} />
                    )}
                </div>
            )}
            {gridWidth > 0 && !showBands && (
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
                        {...gridProps}
                        rowHeight={rowHeight}
                        margin={margin}
                        containerPadding={CONTAINER_PADDING}
                        breakpoints={BREAKPOINTS}
                        cols={BREAKPOINT_COLUMN_COUNTS}
                        onLayoutChange={handleLayoutChange}
                        width={gridWidth}
                        style={{ width: gridWidth }}
                        className={className}
                        layouts={layouts as Partial<Record<DashboardLayoutSize, Layout>>}
                        onWidthChange={handleWidthChange}
                    >
                        {tiles?.map(renderTile)}
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
