import './DashboardV2View.css'

import clsx from 'clsx'
import { type ReactNode, type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useContainerWidth } from 'react-grid-layout'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { DashboardV2Action } from '../access/dashboardV2Access'
import type { DropTarget } from '../grid/dropTargets'
import { GridDragContext, type GridDragState } from '../grid/gridDrag'
import { stackTiles } from '../grid/gridTiles'
import { CapturingTileContext, TileMountContext, createTileMountScheduler } from '../grid/tileMounting'
import { DashboardTileGrid } from '../tiles/DashboardTileGrid'
import { PresentedTile } from '../tiles/PresentedTile'
import { RefreshContext } from '../widgets/refreshContext'
import { DEFAULT_TIME_RANGE, TimeRangeContext } from '../widgets/timeRangeContext'
import { sizeOfWidgets } from '../widgets/widgetSpec'
import { withFolds } from './dashboardEdits'
import { type ImageFormat, downloadDashboardImage } from './dashboardImage'
import { type Dashboard, GRID, activeGridTab, gridTabs } from './dashboardTypes'
import { type DashboardV2Controller, type DashboardV2State, DashboardV2StateContext } from './dashboardV2Context'
import { DashboardV2Tabs } from './DashboardV2Tabs'
import { findTile } from './tileTree'
import { useDashboardRefresh } from './useDashboardRefresh'

// A stacked column is not the saved layout, so only dragging and resizing tiles in it is blocked.
const STACKED_REASON = 'Open this dashboard on a wider screen to arrange tiles'

export interface DashboardV2ViewProps {
    controller: DashboardV2Controller
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
export function DashboardV2View({ controller, header }: DashboardV2ViewProps): JSX.Element {
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
    const [presentedTileId, presentTile] = useState<string | null>(null)
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

    const state = useMemo<DashboardV2State>(() => {
        const { activeTabId, disabledReasonFor: hostReason, onEdit: hostOnEdit, ...rest } = controller
        const disabledReasonFor = (action: DashboardV2Action): string | null =>
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
            presentedTileId,
            presentTile,
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
        presentedTileId,
        refresh.button,
    ])
    const drag = useMemo<GridDragState>(() => ({ dropTarget, setDropTarget }), [dropTarget])
    const [mountScheduler] = useState(createTileMountScheduler)
    useEffect(() => () => mountScheduler.dispose(), [mountScheduler])

    const { activeTab, can, history } = state
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
        <DashboardV2StateContext.Provider value={state}>
            <GridDragContext.Provider value={drag}>
                <TimeRangeContext.Provider value={controller.dashboard.time ?? DEFAULT_TIME_RANGE}>
                    <RefreshContext.Provider value={refresh.count}>
                        <TileMountContext.Provider value={capturing && !capturing.tileId ? null : mountScheduler}>
                            <CapturingTileContext.Provider value={capturing?.tileId ?? null}>
                                <div
                                    ref={rootRef}
                                    data-quill
                                    className={clsx(
                                        'DashboardV2 flex shrink-0 flex-col gap-4 p-4 min-h-full bg-background text-foreground',
                                        downloadingImage && 'DashboardV2View--capturing'
                                    )}
                                >
                                    {header}
                                    <DashboardV2Tabs />
                                    <div
                                        ref={containerRef as RefObject<HTMLDivElement>}
                                        className="DashboardV2View__canvas"
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
                                <PresentedTile />
                            </CapturingTileContext.Provider>
                        </TileMountContext.Provider>
                    </RefreshContext.Provider>
                </TimeRangeContext.Provider>
            </GridDragContext.Provider>
        </DashboardV2StateContext.Provider>
    )
}
