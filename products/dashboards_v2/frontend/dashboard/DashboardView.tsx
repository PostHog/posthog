import './DashboardView.css'

import clsx from 'clsx'
import { type ReactNode, type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useContainerWidth } from 'react-grid-layout'

// TODO(2026-11-25): Replace with quill once it can; the app does not mount quill's ToastProvider yet.
// oxlint-disable-next-line no-restricted-imports
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { FilterBar } from '../filters/bar/FilterBar'
import { type ActiveFilters, FiltersContext, appliedFilters } from '../filters/filtersContext'
import { TimeRangePicker } from '../filters/time/TimeRangePicker'
import type { DropTarget } from '../grid/drag/dropTargets'
import { GridDragContext, type GridDragState } from '../grid/drag/gridDrag'
import { stackTiles } from '../grid/layout/gridTiles'
import { CapturingTileContext, TileMountContext, createTileMountScheduler } from '../grid/tileMounting'
import { DashboardTileGrid } from '../tiles/DashboardTileGrid'
import { TileSlideshow } from '../tiles/TileSlideshow'
import { RefreshContext } from '../widgets/refreshContext'
import { sizeOfWidgets } from '../widgets/widgetSpec'
import { type ImageFormat, downloadDashboardImage } from './actions/dashboardImage'
import { useDashboardRefresh } from './actions/useDashboardRefresh'
import {
    type DashboardAction,
    type DashboardController,
    type DashboardState,
    DashboardStateContext,
} from './dashboardContext'
import { DashboardErrorBoundary } from './DashboardErrorBoundary'
import { DashboardTabs } from './DashboardTabs'
import { type Dashboard, GRID, activeGridTab, gridTabs } from './document/dashboardTypes'
import { findTile } from './document/tileTree'
import { withFolds } from './edits/dashboardEdits'
import { useStableController } from './useStableController'

// A stacked column is not the saved layout, so only dragging and resizing tiles in it is blocked.
const STACKED_REASON = 'Open this dashboard on a wider screen to arrange tiles'

export type DashboardViewProps = DashboardController & {
    /** Rendered above the tabs, inside the dashboard, so it can use the dashboard's own controls. */
    header?: ReactNode
}

function isTyping(target: EventTarget | null): boolean {
    return (
        target instanceof Element &&
        !!target.closest('input, textarea, select, [contenteditable="true"], .monaco-editor')
    )
}

/** The image's file name and the toasts while it is drawn. */
function imageWords(
    dashboard: Dashboard,
    activeTabId: string | null,
    tileId: string | undefined
): { file: string; pending: string; success: string } {
    const tile = tileId ? findTile(dashboard, tileId) : null
    if (tile?.widget.title) {
        const title = tile.widget.title
        return {
            file: `${dashboard.title} ${title}`,
            pending: `Drawing "${title}"`,
            success: `Image of "${title}" downloaded`,
        }
    }
    if (tile) {
        return {
            file: `${dashboard.title} tile`,
            pending: 'Drawing the tile',
            success: 'Image of the tile downloaded',
        }
    }
    const tab = activeGridTab(dashboard, activeTabId).title
    if (gridTabs(dashboard).length > 1) {
        return {
            file: `${dashboard.title} ${tab}`,
            pending: `Drawing every tile on the "${tab}" tab`,
            success: `Image of the "${tab}" tab downloaded`,
        }
    }
    return { file: dashboard.title, pending: 'Drawing every tile', success: 'Image downloaded' }
}

/** A whole dashboard: tabs and grid. Its own state is only what the screen and a drag in progress decide. */
export function DashboardView(props: DashboardViewProps): JSX.Element {
    return (
        <DashboardErrorBoundary dashboard={props.dashboard}>
            <DashboardViewContent {...props} />
        </DashboardErrorBoundary>
    )
}

function DashboardViewContent({ header, ...props }: DashboardViewProps): JSX.Element {
    const controller = useStableController(props)
    const { width, containerRef, mounted } = useContainerWidth()
    const stacked = width > 0 && width < GRID.stackBelowPx
    const [dropTarget, setDropTarget] = useState<DropTarget | null>(null)
    const sizeOf = useMemo(() => sizeOfWidgets(controller.widgets), [controller.widgets])
    // Which sections this person opened or closed. Only the screen needs it, so the host never sees it.
    const [folds, setFolds] = useState<Record<string, boolean>>({})
    const onSectionFoldedChange = useCallback(
        (id: string, collapsed: boolean) => setFolds((previous) => ({ ...previous, [id]: collapsed })),
        []
    )
    const rootRef = useRef<HTMLDivElement>(null)
    const [slideshowTileId, showSlideshow] = useState<string | null>(null)
    const refresh = useDashboardRefresh(controller.refresh)
    // A capture mounts what it shows, so the image has no placeholders: the whole tab, or with `tileId` that tile only.
    const [capturing, setCapturing] = useState<{ tileId?: string } | null>(null)
    const downloadingImage = capturing !== null
    const downloadImage = useCallback(
        async (format: ImageFormat, tileId?: string): Promise<void> => {
            const page = rootRef.current
            const root = tileId ? page?.querySelector<HTMLElement>(`[data-dv2-tile="${CSS.escape(tileId)}"]`) : page
            if (!root) {
                return
            }
            setCapturing({ tileId })
            try {
                const words = imageWords(controller.dashboard, controller.activeTabId, tileId)
                await lemonToast.promise(downloadDashboardImage(root, words.file, format), {
                    pending: words.pending,
                    success: words.success,
                    error: 'Could not create the image. Try again.',
                })
            } catch {
                // The toast already says it failed.
            } finally {
                setCapturing(null)
            }
        },
        [controller]
    )

    const state = useMemo<DashboardState>(() => {
        const { activeTabId, disabledReasonFor: hostReason, onEdit: hostOnEdit, ...rest } = controller
        const disabledReasonFor = (action: DashboardAction): string | null =>
            hostReason(action) ?? (stacked && action === 'placeTiles' ? STACKED_REASON : null)
        const view = (dashboard: Dashboard): Dashboard => withFolds(dashboard, folds, sizeOf)
        const dashboard = view(rest.dashboard)
        return {
            ...rest,
            dashboard,
            activeTab: activeGridTab(dashboard, activeTabId),
            sizeOf,
            disabledReasonFor,
            can: (action) => disabledReasonFor(action) === null,
            onEdit: (edit) => hostOnEdit(edit, view),
            onSectionFoldedChange,
            downloadImage: (format, tileId) => void downloadImage(format, tileId),
            downloadingImage,
            slideshowTileId,
            showSlideshow,
            refresh: refresh.button,
        }
    }, [
        controller,
        stacked,
        sizeOf,
        folds,
        onSectionFoldedChange,
        downloadImage,
        downloadingImage,
        slideshowTileId,
        refresh.button,
    ])
    const drag = useMemo<GridDragState>(() => ({ dropTarget, setDropTarget }), [dropTarget])
    const [mountScheduler] = useState(createTileMountScheduler)
    useEffect(() => () => mountScheduler.dispose(), [mountScheduler])

    const { activeTab, can, history } = state
    const savedFilters = controller.dashboard.filters
    const filterValues = controller.filters?.values
    const filtersOn = !!controller.filters && !!controller.dashboard.allowFilters
    const applied = useMemo(
        () => (filtersOn && filterValues ? appliedFilters(savedFilters ?? [], filterValues) : []),
        [filtersOn, savedFilters, filterValues]
    )
    const time = controller.timeRange?.value ?? controller.dashboard.time
    const activeFilters = useMemo<ActiveFilters>(() => ({ time, filters: applied }), [time, applied])
    const tiles = useMemo(
        () => (stacked ? stackTiles(activeTab.tiles, GRID.columns, sizeOf) : activeTab.tiles),
        [stacked, activeTab.tiles, sizeOf]
    )

    const undoable = can('undo') ? history : undefined
    useEffect(() => {
        if (!undoable) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const key = event.key.toLowerCase()
            if (isTyping(event.target) || !(event.metaKey || event.ctrlKey) || (key !== 'z' && key !== 'y')) {
                return
            }
            event.preventDefault()
            if (key === 'y' || event.shiftKey) {
                if (can('redo')) {
                    undoable.onRedo()
                }
            } else {
                undoable.onUndo()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [undoable, can])

    return (
        <DashboardStateContext.Provider value={state}>
            <GridDragContext.Provider value={drag}>
                <FiltersContext.Provider value={activeFilters}>
                    <RefreshContext.Provider value={refresh.count}>
                        <TileMountContext.Provider value={capturing && !capturing.tileId ? null : mountScheduler}>
                            <CapturingTileContext.Provider value={capturing?.tileId ?? null}>
                                <div
                                    ref={rootRef}
                                    data-quill
                                    className={clsx(
                                        'DashboardV2 flex shrink-0 flex-col gap-4 p-4 min-h-full bg-background text-foreground',
                                        downloadingImage && 'DashboardView--capturing'
                                    )}
                                >
                                    {header}
                                    {(filtersOn || controller.timeRange) && (
                                        <div className="flex items-start gap-2">
                                            {controller.timeRange && (
                                                <TimeRangePicker
                                                    value={time}
                                                    onChange={controller.timeRange.onChange}
                                                    ranges={controller.timeRange.ranges}
                                                    timezone={controller.timeRange.timezone}
                                                />
                                            )}
                                            <div className="min-w-0 flex-1">
                                                {filtersOn && controller.filters && (
                                                    <FilterBar
                                                        filters={savedFilters ?? []}
                                                        types={controller.filters.types}
                                                        values={controller.filters.values}
                                                        onValueChange={controller.filters.onValueChange}
                                                        onAdd={
                                                            can('addFilter')
                                                                ? (filter) =>
                                                                      state.onEdit({ edit: 'addFilter', filter })
                                                                : undefined
                                                        }
                                                        onRemove={
                                                            can('removeFilter')
                                                                ? (id) => state.onEdit({ edit: 'removeFilter', id })
                                                                : undefined
                                                        }
                                                    />
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    <DashboardTabs />
                                    <div
                                        ref={containerRef as RefObject<HTMLDivElement>}
                                        className="DashboardView__canvas"
                                    >
                                        {mounted && width > 0 && (
                                            <DashboardTileGrid
                                                key={`${activeTab.id}-${stacked ? 'stacked' : 'grid'}`}
                                                gridId={activeTab.id}
                                                tiles={tiles}
                                                cols={GRID.columns}
                                                width={width}
                                                editable={can('placeTiles')}
                                            />
                                        )}
                                    </div>
                                </div>
                                <TileSlideshow />
                            </CapturingTileContext.Provider>
                        </TileMountContext.Provider>
                    </RefreshContext.Provider>
                </FiltersContext.Provider>
            </GridDragContext.Provider>
        </DashboardStateContext.Provider>
    )
}
