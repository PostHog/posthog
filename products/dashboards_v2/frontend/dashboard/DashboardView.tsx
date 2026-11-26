import './DashboardView.css'

import clsx from 'clsx'
import posthog from 'posthog-js'
import {
    type ReactNode,
    type RefObject,
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from 'react'
import { useContainerWidth } from 'react-grid-layout'

// TODO(2026-11-25): Replace with quill once it can; the app does not mount quill's ToastProvider yet.
// oxlint-disable-next-line no-restricted-imports
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getJSHeapMemory } from 'lib/utils/dom'

import { FilterBar } from '../filters/bar/FilterBar'
import { type ActiveFilters, FiltersContext, appliedFilters } from '../filters/filtersContext'
import { TimeRangePicker } from '../filters/time/TimeRangePicker'
import type { DropTarget } from '../grid/drag/dropTargets'
import { GridDragContext, type GridDragState } from '../grid/drag/gridDrag'
import { stackTiles } from '../grid/layout/gridTiles'
import { CapturingTileContext, TileMountContext, createTileMountScheduler } from '../grid/tileMounting'
import { PanelHostContext } from '../panels/core/panelHostContext'
import { sizeOfPanels } from '../panels/core/panelSpec'
import { DashboardTileGrid } from '../tiles/DashboardTileGrid'
import { TileSlideshow } from '../tiles/TileSlideshow'
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
import { everyTile, findTile } from './document/tileTree'
import { withFolds } from './edits/dashboardEdits'
import { type DashboardLoadTrigger, createDashboardTiming } from './timing/dashboardTiming'
import { useStableController } from './useStableController'

// A stacked column is not the saved layout, so only dragging and resizing tiles in it is blocked.
const STACKED_REASON = 'Open this dashboard on a wider screen to arrange tiles'

export type DashboardViewProps = DashboardController & {
    /**
     * Where this dashboard is shown, such as `dashboard-v2-scene` or `apm`. Every load timing event carries it, so the
     * same primitives can be compared across products. Keep it stable: it is an analytics property value.
     */
    surface: string
    /**
     * Shows each panel's sample data instead of running its queries, while there is no real data to show, such as in
     * a project that has not sent any events yet.
     */
    sampleData?: boolean
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
    if (tile?.panel.title) {
        const title = tile.panel.title
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

function DashboardViewContent({ header, surface, sampleData = false, ...props }: DashboardViewProps): JSX.Element {
    const controller = useStableController(props)
    const { width, containerRef, mounted } = useContainerWidth()
    const stacked = width > 0 && width < GRID.stackBelowPx
    const [dropTarget, setDropTarget] = useState<DropTarget | null>(null)
    const sizeOf = useMemo(() => sizeOfPanels(controller.panels), [controller.panels])
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
    const timingContext = useRef({ surface, tileCount: 0 })
    const [timing] = useState(() =>
        createDashboardTiming({
            isSettled: mountScheduler.settled,
            onReport: (report) =>
                // pinned: analytics event and property names. Renaming them breaks the dashboards that read them.
                posthog.capture('dashboard v2 loaded', {
                    surface: timingContext.current.surface,
                    tile_count: timingContext.current.tileCount,
                    trigger: report.trigger,
                    status: report.status,
                    duration_ms: report.durationMs,
                    first_result_ms: report.firstResultMs,
                    query_count: report.queryCount,
                    cached_query_count: report.cachedQueryCount,
                    failed_query_count: report.failedQueryCount,
                    slowest_query_ms: report.slowestQueryMs,
                    long_task_count: report.longTaskCount,
                    long_task_ms: report.longTaskMs,
                    page_hidden: report.pageHidden,
                    ...getJSHeapMemory(),
                }),
        })
    )
    useEffect(() => () => timing.dispose(), [timing])
    const panelHost = useMemo(
        () => ({ refresh: refresh.count, sampleData, timing }),
        [refresh.count, sampleData, timing]
    )

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
    timingContext.current = { surface, tileCount: everyTile(activeTab.tiles).length }

    // A layout effect runs before the tiles' own effects start their queries, so the load is open to count them.
    const loadInputs = useRef<{ refresh: number; filters: ActiveFilters; tabId: string } | null>(null)
    useLayoutEffect(() => {
        const previous = loadInputs.current
        loadInputs.current = { refresh: refresh.count, filters: activeFilters, tabId: activeTab.id }
        let trigger: DashboardLoadTrigger | null = null
        if (!previous) {
            trigger = 'load'
        } else if (previous.tabId !== activeTab.id) {
            trigger = 'tab'
        } else if (previous.refresh !== refresh.count) {
            trigger = 'refresh'
        } else if (previous.filters !== activeFilters) {
            trigger = 'filters'
        }
        if (trigger) {
            timing.begin(trigger)
        }
    }, [timing, refresh.count, activeFilters, activeTab.id])

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
                    <PanelHostContext.Provider value={panelHost}>
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
                                                                      state.onEdit({
                                                                          edit: 'addFilter',
                                                                          filter,
                                                                      })
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
                    </PanelHostContext.Provider>
                </FiltersContext.Provider>
            </GridDragContext.Provider>
        </DashboardStateContext.Provider>
    )
}
