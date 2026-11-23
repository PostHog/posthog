import '../DashboardV2.scss'

import { type CSSProperties, type ReactNode, type RefObject, useEffect, useMemo } from 'react'
import { useContainerWidth } from 'react-grid-layout'

import {
    type DashboardV2Controller,
    DashboardV2DragContext,
    type DashboardV2DragState,
    type DashboardV2State,
    DashboardV2StateContext,
} from '../dashboardV2Context'
import { stackTiles } from '../layout/dashboardEdits'
import { GRID, gapPxOf } from '../layout/dashboardTypes'
import { DashboardV2Tabs } from './DashboardV2Tabs'
import { TileGrid } from './TileGrid'

export interface DashboardV2ViewProps {
    controller: DashboardV2Controller
    /** Rendered above the tabs, inside the dashboard, so it can use the dashboard's own controls. */
    header?: ReactNode
}

/** A whole dashboard: tabs and grid. It holds no state of its own beyond a gesture in progress. */
export function DashboardV2View({ controller, header }: DashboardV2ViewProps): JSX.Element {
    const {
        dashboard,
        activeTab,
        disabledReasonFor,
        onEdit,
        onActiveTabChange,
        onSectionFoldedChange,
        onStackedChange,
        history,
        dropTarget,
        onDropTargetChange,
    } = controller
    const state = useMemo<DashboardV2State>(
        () => ({
            dashboard,
            activeTab,
            disabledReasonFor,
            onEdit,
            onActiveTabChange,
            onSectionFoldedChange,
            onStackedChange,
            history,
        }),
        [
            dashboard,
            activeTab,
            disabledReasonFor,
            onEdit,
            onActiveTabChange,
            onSectionFoldedChange,
            onStackedChange,
            history,
        ]
    )
    const drag = useMemo<DashboardV2DragState>(
        () => ({ dropTarget, onDropTargetChange }),
        [dropTarget, onDropTargetChange]
    )

    const { width, containerRef, mounted } = useContainerWidth()
    const stacked = width > 0 && width < GRID.stackBelowPx
    const tiles = useMemo(
        () => (stacked ? stackTiles(activeTab.tiles, GRID.columns) : activeTab.tiles),
        [stacked, activeTab.tiles]
    )

    useEffect(() => {
        onStackedChange?.(stacked)
    }, [stacked, onStackedChange])

    return (
        <DashboardV2StateContext.Provider value={state}>
            <DashboardV2DragContext.Provider value={drag}>
                <div
                    data-quill
                    className="DashboardV2 flex flex-col gap-4 p-4 min-h-full bg-background text-foreground"
                    // The tile gap comes from the dashboard's JSON, so CSS reads it from a variable rather than a class.
                    // oxlint-disable-next-line react/forbid-dom-props
                    style={{ '--dv2-gap': `${gapPxOf(dashboard)}px` } as CSSProperties}
                >
                    {header}
                    <DashboardV2Tabs />
                    <div ref={containerRef as RefObject<HTMLDivElement>} className="DashboardV2__canvas">
                        {mounted && width > 0 && (
                            <TileGrid
                                key={`${activeTab.id}-${stacked ? 'stacked' : 'grid'}`}
                                gridId={activeTab.id}
                                tiles={tiles}
                                cols={GRID.columns}
                                width={width}
                                editable={disabledReasonFor('placeTiles') === null && !stacked}
                            />
                        )}
                    </div>
                </div>
            </DashboardV2DragContext.Provider>
        </DashboardV2StateContext.Provider>
    )
}
