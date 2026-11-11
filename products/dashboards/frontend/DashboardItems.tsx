import clsx from 'clsx'
import { useActions, useAsyncActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { RefObject, memo, useCallback, useEffect, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'
import { GridLayout, Responsive as ReactGridLayout } from 'react-grid-layout'
import type { Layout, LayoutItem } from 'react-grid-layout'
import { calcGridItemPosition, type PositionStrategy, setTransform } from 'react-grid-layout/core'

import 'scenes/dashboard/DashboardItems.scss'
import { ApiError } from 'lib/api'
import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { useResizeHandleScrollbarPassThrough } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { TileDecorations } from 'lib/components/TileDecorations/TileDecorations'
import { objectsEqual } from 'lib/utils/objects'
import { reportDashboardTileRepositioned } from 'scenes/dashboard/dashboardEvents'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import {
    BREAKPOINTS,
    BREAKPOINT_COLUMN_COUNTS,
    getInsightQueryError,
    isWidgetTileVisibleOnPlacement,
} from 'scenes/dashboard/dashboardUtils'
import { useDashboardLayoutInteraction } from 'scenes/dashboard/useDashboardLayoutInteraction'
import { useDragAutoScroll } from 'scenes/dashboard/useDragAutoScroll'
import { Scene } from 'scenes/sceneTypes'
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
import { type LayoutGesturePerformance, LayoutGestureMonitor } from 'products/dashboards/frontend/dashboardPerformance'
import { getGroupTitlesByTileId, hasTileDecorations } from 'products/dashboards/frontend/dashboardTileGroups'
import { type DashboardSection, getSectionGroupKey } from 'products/dashboards/frontend/dashboardTileSections'
import { useClickToMoveTile } from 'products/dashboards/frontend/useClickToMoveTile'
import { useDashboardContainerWidth } from 'products/dashboards/frontend/useDashboardContainerWidth'
import { TAKE_OUT_DROP_ZONE_KEY, useTileGroupDrag } from 'products/dashboards/frontend/useTileGroupDrag'

import { DashboardWidgetItem } from './components/DashboardWidgetItem/DashboardWidgetItem'
import { getDashboardAddTileOptions } from './dashboardAddTileOptions'
import { DashboardEmptyGroupAddButton } from './DashboardEmptyGroupAddButton'
import { DashboardButtonTileItem } from './items/DashboardButtonTileItem'
import { DashboardErrorTileItem } from './items/DashboardErrorTileItem'
import { getDashboardWidgetFetchDisplayError } from './widgets/constants'

const ROW_HEIGHT = 80
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
        copyGroupToDashboardLoading,
        widgetResultsByTileId,
        widgetRefreshStatus,
        scrollToBottomSignal,
        renamingTileGroupKey,
        sizeKey,
        tileGroupSectionsEnabled,
        tileGroupSections,
        tileGroupSectionLayouts,
        collapsedTileGroupKeys,
        tileGroupMoveOptions,
        activeTileGroupTab,
        queryLoadQueue,
        isEditablePlacement,
        canEditLayout,
        carryingTile,
        showTextTileModal,
        showImageTileModal,
        showButtonTileModal,
        addWidgetModalOpen,
    } = useValues(dashboardLogic)
    const canCrossFilter = placement === DashboardPlacement.Dashboard && !isSharedView()
    useMountedLogic(
        biDashboardCrossFilterLogic({
            dashboardId: dashboard?.id ?? 0,
            tiles: canCrossFilter ? (tiles ?? []) : [],
            loadQueue: queryLoadQueue,
        })
    )
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
        renameTileGroup,
        setRenamingTileGroupKey,
        setAddTargetTileGroupKey,
        openAddInsightModal,
        openTextTileModal,
        openImageTileModal,
        openButtonTileModal,
        setAddWidgetModalOpen,
        removeTileGroup,
        toggleTileGroup,
        selectTileGroupTab,
        updateTileGroupSectionLayout,
        moveTileToSection,
        setCarryingTile,
        undoLayoutChange,
        redoLayoutChange,
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

    // cannot click links when dragging and 250ms after
    const isDragging = useRef(false)
    // While a drag/resize is in progress the grid drives itself from its own internal state and ignores the
    // `layouts` prop, so pushing layout updates to the store mid-gesture only triggers expensive full re-renders
    // (every InsightCard) that make the dragged tile lag the cursor. Stash the latest layout and commit once on stop.
    const dragEndTimeout = useRef<number | null>(null)
    const layoutGesture = useRef<LayoutGestureMonitor | null>(null)
    const { startAutoScroll, autoScrollOnDrag, stopAutoScroll } = useDragAutoScroll()
    const lastScrollSignalRef = useRef(scrollToBottomSignal)

    useEffect(() => {
        return () => {
            if (dragEndTimeout.current) {
                window.clearTimeout(dragEndTimeout.current)
            }
            layoutGesture.current?.cancel()
        }
    }, [])

    const startLayoutGesture = useCallback((): void => {
        layoutGesture.current?.cancel()
        layoutGesture.current = new LayoutGestureMonitor().start()
    }, [])

    const finishLayoutGesture = useCallback(
        (report: ((gesturePerformance?: LayoutGesturePerformance) => void) | null, releasedAt: number): void => {
            const gesture = layoutGesture.current
            layoutGesture.current = null
            if (!report) {
                gesture?.cancel()
            } else if (gesture) {
                gesture.finish(report, releasedAt)
            } else {
                report()
            }
        },
        []
    )

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
    const { width: gridWidth, containerRef } = useDashboardContainerWidth()
    const showBands = tileGroupSections.length > 0
    const activeTabIndex = tileGroupSections.findIndex((section) => getSectionGroupKey(section) === activeTileGroupTab)
    // Inputs keep their own text undo, so the layout shortcuts stand down while one has focus. A modal or a
    // carried tile sits over the grid, so an undo there would move tiles the viewer cannot see or is holding.
    // Undo belongs to the dashboard page: an embed shows no Undo controls and can share a page with other dashboards.
    const layoutShortcutsEnabled =
        canEditLayout &&
        placement === DashboardPlacement.Dashboard &&
        !carryingTile &&
        !showTextTileModal &&
        !showImageTileModal &&
        !showButtonTileModal &&
        !addWidgetModalOpen
    useShortcut({
        name: 'DashboardUndoLayoutChange',
        keybind: [keyBinds.undo],
        intent: 'Undo layout change',
        interaction: 'function',
        callback: undoLayoutChange,
        scope: Scene.Dashboard,
        disabled: !layoutShortcutsEnabled,
        ignoreInEditable: true,
    })
    useShortcut({
        name: 'DashboardRedoLayoutChange',
        keybind: [keyBinds.redo],
        intent: 'Redo layout change',
        interaction: 'function',
        callback: redoLayoutChange,
        scope: Scene.Dashboard,
        disabled: !layoutShortcutsEnabled,
        ignoreInEditable: true,
    })
    const className = clsx(
        'mb-8',
        canEditLayout ? 'dashboard-layout-editable dashboard-drop-space-end' : 'dashboard-layout-static'
    )

    const { gridCompactor, handleLayoutChange, startInteraction, finishInteraction } = useDashboardLayoutInteraction({
        enabled: canEditLayout,
        layoutCompaction: dashboard?.customization?.layout_compaction,
        // Each band grid reports only its own tiles.
        updateLayouts: showBands ? updateTileGroupSectionLayout : stageLayouts,
    })
    const onCopyGroupToDashboard = canEditDashboard && isEditablePlacement ? copyGroupToDashboard : undefined
    const onChangeGroupDisplay = canEditDashboard && isEditablePlacement ? changeTileGroupDisplay : undefined
    const onRenameTileGroup = canEditDashboard && isEditablePlacement ? renameTileGroup : undefined
    const getAddTileOptions =
        canEditDashboard && isEditablePlacement
            ? (groupKey: string) =>
                  getDashboardAddTileOptions({
                      onAddInsight: openAddInsightModal,
                      onAddText: openTextTileModal,
                      onAddImage: openImageTileModal,
                      onAddButton: openButtonTileModal,
                      setAddWidgetModalOpen,
                  }).map((option) => ({
                      key: option.key,
                      label: option.label,
                      onClick: () => {
                          setAddTargetTileGroupKey(groupKey)
                          option.onClick()
                      },
                  }))
            : undefined
    const getEmptyGroupAddAction =
        canEditDashboard && isEditablePlacement
            ? (groupKey: string) => <DashboardEmptyGroupAddButton groupKey={groupKey} />
            : undefined
    const onRemoveTileGroup = canEditDashboard && isEditablePlacement ? removeTileGroup : undefined

    const gridGap = getDashboardTileSpacingGap(dashboard?.customization?.tile_spacing)
    const margin = useMemo<[number, number]>(() => [gridGap, gridGap], [gridGap])

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

    const showResizeHandles = canEditLayout
    const showEditingControls = isEditablePlacement
    const showDetailsControls =
        placement !== DashboardPlacement.Export &&
        placement !== DashboardPlacement.Public &&
        !getCurrentExporterData()?.hideExtraDetails

    const dragConfig = useMemo(
        () => ({
            enabled: canEditLayout,
            handle: '.CardMeta,.DashboardTileCard__body,.WidgetCard__header,.drag-handle',
            // Text inside a tile stays selectable instead of starting a drag.
            cancel: 'a,table,button,input,textarea,select,p,h4,[contenteditable="true"],[role="textbox"],.ProseMirror,.LemonMarkdown,.Popover',
            bounded: !showBands || activeTabIndex >= 0,
        }),
        [canEditLayout, showBands, activeTabIndex]
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
        rowHeight: ROW_HEIGHT,
        margin,
        layout: layouts.sm,
        moveTileToSection: (tileId, sectionKey, cell) => moveTileToSection(tileId, sectionKey, cell, 'drag'),
        restoreLayout: (layout) => stageLayouts({ sm: layout }),
    })
    const boundedStrategy = useMemo(() => sidewaysBoundedStrategy(gridWidth), [gridWidth])
    const { tileMoveInputRef, carryHeldDrag } = useClickToMoveTile({
        containerRef: containerRef as RefObject<HTMLElement>,
        enabled: dragConfig.enabled,
        handleSelector: dragConfig.handle,
        cancelSelector: dragConfig.cancel,
        onCarryingChange: setCarryingTile,
    })

    const resizeConfig = useMemo(
        () => ({
            enabled: canEditLayout,
            handles: ['s', 'e', 'se', 'w', 'sw'] as const,
        }),
        [canEditLayout]
    )

    useResizeHandleScrollbarPassThrough(canEditLayout)

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

    // Toggled on the DOM rather than in state, so a gesture does not re-render every tile.
    const setLayoutGestureActive = useCallback(
        (active: boolean): void => {
            containerRef.current?.classList.toggle('dashboard-layout-gesture', active)
        },
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- containerRef is a stable ref
        []
    )

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
            rowHeight: ROW_HEIGHT,
            margin,
            containerPadding: CONTAINER_PADDING,
        }),
        [bandBreakpoint, margin]
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
            setLayoutGestureActive(true)
            startInteraction(layout, newItem, 'resize')
            startLayoutGesture()
        },
        [startInteraction, setLayoutGestureActive, startLayoutGesture]
    )

    const handleResizeStop = useCallback(() => {
        const releasedAt = performance.now()
        setLayoutGestureActive(false)
        finishInteraction()
        const dashboardId = dashboard?.id
        finishLayoutGesture(
            dashboardId
                ? (gesturePerformance) =>
                      reportDashboardTileRepositioned(dashboardId, 'resized', 'drag', gesturePerformance)
                : null,
            releasedAt
        )
    }, [dashboard?.id, finishInteraction, finishLayoutGesture, setLayoutGestureActive])

    // Toggled on the DOM rather than in state, so a drag does not re-render every tile.
    const setTileDragActive = useCallback(
        (active: boolean, element: HTMLElement | null): void => {
            containerRef.current?.classList.toggle('dashboard-tile-drag', active)
            element?.classList.toggle('dashboard-tile-moving', active)
        },
        [containerRef]
    )

    // The grid's placeholder sits where the tile lands once tiles stack up, which in an empty column is the top,
    // so it looks stuck while the tile moves away. This preview follows the cell under the tile instead.
    // The grid without sections uses the same columns, margin and padding, so `bandGridConfig` places its preview too.
    const showDragPreview = useCallback(
        (item: LayoutItem | null, element: HTMLElement | null): void => {
            const preview = element
                ?.closest('[data-dashboard-grid-frame]')
                ?.querySelector<HTMLElement>(':scope > .DashboardDragPreview')
            if (!preview || !item) {
                return
            }
            const { top, left, width, height } = calcGridItemPosition(
                { ...bandGridConfig, containerWidth: gridWidth, maxRows: Infinity },
                item.x,
                item.y,
                item.w,
                item.h
            )
            preview.style.transform = `translate(${left}px, ${top}px)`
            preview.style.width = `${width}px`
            preview.style.height = `${height}px`
            preview.hidden = false
        },
        [bandGridConfig, gridWidth]
    )

    const hideDragPreviews = useCallback((): void => {
        containerRef.current?.querySelectorAll<HTMLElement>('.DashboardDragPreview').forEach((preview) => {
            preview.hidden = true
        })
    }, [containerRef])

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
            setLayoutGestureActive(true)
            setTileDragActive(true, element)
            showDragPreview(newItem, element)
            startInteraction(layout, newItem, 'drag')
            startLayoutGesture()
            startTileDrag(newItem, element)
            startAutoScroll()
            carryHeldDrag(element)
        },
        [
            startInteraction,
            startLayoutGesture,
            startTileDrag,
            startAutoScroll,
            carryHeldDrag,
            setLayoutGestureActive,
            setTileDragActive,
            showDragPreview,
        ]
    )

    const handleDrag = useCallback(
        (
            _layout: Layout,
            _oldItem: LayoutItem | null,
            newItem: LayoutItem | null,
            _placeholder: LayoutItem | null,
            e: Event,
            element: HTMLElement | null
        ) => {
            isDragging.current = true
            showDragPreview(newItem, element)
            trackTileDrag(e)
            if (dragEndTimeout.current) {
                window.clearTimeout(dragEndTimeout.current)
            }
            autoScrollOnDrag(e)
        },
        [autoScrollOnDrag, trackTileDrag, showDragPreview]
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
            const releasedAt = performance.now()
            stopAutoScroll()
            if (dragEndTimeout.current) {
                window.clearTimeout(dragEndTimeout.current)
            }
            dragEndTimeout.current = window.setTimeout(() => {
                isDragging.current = false
            }, 250)
            // The drop target is read from the grids as they look now, so their drop space stays until it is.
            const leftSection = finishTileDrag(newItem, element, event)
            // A tile that left its section saves as one move from where the drag started. Saving the source
            // grid's layout first would record a second undo step, with the tile at the row the drag reached.
            finishInteraction({ discardLayout: leftSection })
            setLayoutGestureActive(false)
            hideDragPreviews()
            setTileDragActive(false, element)
            const input = tileMoveInputRef.current
            const dashboardId = dashboard?.id
            finishLayoutGesture(
                dashboardId && input !== 'canceled'
                    ? (gesturePerformance) =>
                          reportDashboardTileRepositioned(dashboardId, 'moved', input, gesturePerformance)
                    : null,
                releasedAt
            )
        },
        [
            dashboard?.id,
            finishInteraction,
            finishLayoutGesture,
            finishTileDrag,
            setLayoutGestureActive,
            stopAutoScroll,
            tileMoveInputRef,
            hideDragPreviews,
            setTileDragActive,
        ]
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
                    isDraggingRef={isDragging}
                    onEdit={tileActions.edit}
                    onMoveToDashboard={commonTileProps.moveToDashboard}
                    tileGroupMoveOptions={commonTileProps.tileGroupMoveOptions}
                    onMoveToTileGroup={commonTileProps.moveToTileGroup}
                    onCopyToDashboard={commonTileProps.copyToDashboard}
                    onDuplicate={tileActions.duplicate}
                    onRemove={commonTileProps.removeFromDashboard}
                    showResizeHandles={commonTileProps.showResizeHandles}
                    showEditingControls={commonTileProps.showEditingControls}
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
                    result={runResult?.result}
                    error={getDashboardWidgetFetchDisplayError(runResult?.error ?? refreshState?.error)}
                    loading={!!refreshState?.loading}
                    lastFetchedAt={refreshState?.fetchedAt}
                    dashboardFilters={effectiveEditBarFilters}
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
        return (
            <div
                className={clsx('relative', isDraggingOutOfSection && '[&_.DashboardDragPreview]:hidden')}
                data-dashboard-section-grid={section.key}
                data-dashboard-grid-frame
                style={frozenSourceGrid?.key === section.key ? { height: frozenSourceGrid.height } : undefined}
            >
                {canEditLayout && (
                    <DashboardGridBackground
                        width={gridWidth}
                        cols={BREAKPOINT_COLUMN_COUNTS.sm}
                        rowHeight={ROW_HEIGHT}
                        margin={margin}
                    />
                )}
                {canEditLayout && <div className="DashboardDragPreview" aria-hidden hidden />}
                {/* Not Responsive: its layout copy and the inner grid's can swap on every render while tiles stream in. */}
                <GridLayout
                    {...gridProps}
                    // The grid takes a new tile's position from `layout`, so a stable key lets tiles stream
                    // into a band without a remount that resets every chart already in it.
                    key={section.key}
                    width={gridWidth}
                    positionStrategy={boundedStrategy}
                    className={clsx(
                        canEditLayout ? 'dashboard-layout-editable' : 'dashboard-layout-static',
                        canEditLayout && (isLastSection ? 'dashboard-drop-space-end' : 'dashboard-drop-space-between'),
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
            onRenameTileGroup={onRenameTileGroup}
            renamingTileGroupKey={renamingTileGroupKey}
            onRenamingTileGroupKeyChange={setRenamingTileGroupKey}
            onRemoveTileGroup={onRemoveTileGroup}
            copyToDestinations={copyToDestinations}
            onCopyGroupToDashboard={onCopyGroupToDashboard}
            copyLoading={copyGroupToDashboardLoading}
            onChangeGroupDisplay={onChangeGroupDisplay}
            getAddTileOptions={getAddTileOptions}
            getEmptyGroupAddAction={getEmptyGroupAddAction}
        >
            {renderSectionGrid(section, index)}
        </DashboardTileSectionBand>
    )

    return (
        <div className="dashboard-items-wrapper" ref={containerRef as RefObject<HTMLDivElement>}>
            {gridWidth > 0 && activeTabIndex >= 0 && (
                <div className={clsx(showDecorationSpace && 'mt-10', 'mb-8')}>
                    <DashboardTileGroupTabs
                        sections={tileGroupSections}
                        activeSectionKey={tileGroupSections[activeTabIndex].key}
                        onSelect={selectTileGroupTab}
                        onRenameGroup={onRenameTileGroup}
                        renamingGroupKey={renamingTileGroupKey}
                        onRenamingGroupKeyChange={setRenamingTileGroupKey}
                        onRemoveGroup={onRemoveTileGroup}
                        copyToDestinations={copyToDestinations}
                        onCopyGroupToDashboard={onCopyGroupToDashboard}
                        copyLoading={copyGroupToDashboardLoading}
                        onChangeGroupDisplay={onChangeGroupDisplay}
                        getAddTileOptions={getAddTileOptions}
                        getEmptyGroupAddAction={getEmptyGroupAddAction}
                    >
                        {renderSectionGrid(tileGroupSections[activeTabIndex], activeTabIndex)}
                    </DashboardTileGroupTabs>
                </div>
            )}
            {gridWidth > 0 && showBands && activeTabIndex < 0 && (
                <div className={clsx('flex flex-col gap-4 mb-8', showDecorationSpace && 'mt-10')}>
                    {tileGroupSections.map(renderSection)}
                    {showTakeOutDropZone && (
                        <TileGroupTakeOutDropZone isDropTarget={dropTargetKey === TAKE_OUT_DROP_ZONE_KEY} />
                    )}
                </div>
            )}
            {gridWidth > 0 && !showBands && (
                <div className={clsx('relative', showDecorationSpace && 'mt-10')} data-dashboard-grid-frame>
                    {canEditLayout && (
                        <DashboardGridBackground
                            width={gridWidth}
                            cols={BREAKPOINT_COLUMN_COUNTS.sm}
                            rowHeight={ROW_HEIGHT}
                            margin={margin}
                        />
                    )}
                    {canEditLayout && <div className="DashboardDragPreview" aria-hidden hidden />}

                    <ReactGridLayout
                        {...gridProps}
                        rowHeight={ROW_HEIGHT}
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
            <TileMoveHint />
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

// Reads carryingTile itself, so a carry starting or ending re-renders only this pill and not every tile in the grid.
// The portal keeps the pill out of the grid's subtree, where inserting a node restyles every tile.
function TileMoveHint(): JSX.Element | null {
    const { carryingTile } = useValues(dashboardLogic)
    if (!carryingTile) {
        return null
    }
    return createPortal(
        // Ignores the pointer, because the next click drops the tile wherever this pill is.
        <div
            role="status"
            className="pointer-events-none fixed bottom-6 left-1/2 z-top flex -translate-x-1/2 items-center gap-2 rounded-full border bg-surface-primary px-3 py-1 text-sm shadow"
        >
            <span>Click to drop the tile</span>
            <span className="text-secondary">· Esc to cancel</span>
        </div>,
        document.body
    )
}
