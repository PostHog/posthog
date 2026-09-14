import { useCallback, useMemo, useRef } from 'react'
import type { MutableRefObject } from 'react'
import { cloneLayoutItem } from 'react-grid-layout'
import type { Compactor, Layout, LayoutItem } from 'react-grid-layout'

import {
    getResizeNeighbors,
    pinUnmovedItemsToBaseline,
    resizeNeighborToFitRow,
    restoreUnmovedItemPositions,
} from 'scenes/dashboard/dashboardResizeCompactor'
import type { ResizeNeighbors } from 'scenes/dashboard/dashboardResizeCompactor'

import type { DashboardLayoutSize } from '~/types'

import { DashboardGridCompaction, getDashboardGridCompactor } from 'products/dashboards/frontend/dashboardCustomization'
import type { DashboardInteractionKind } from 'products/dashboards/frontend/dashboardCustomization'

interface UseDashboardLayoutInteractionProps {
    layoutEditMode: boolean
    layoutCompaction?: DashboardGridCompaction
    updateLayouts: (layouts: Partial<Record<DashboardLayoutSize, Layout>>) => void
}

interface DashboardLayoutInteraction {
    gridCompactor: Compactor
    handleLayoutChange: (_: unknown, newLayouts: Partial<Record<DashboardLayoutSize, Layout>>) => void
    interactionInProgress: MutableRefObject<boolean>
    startInteraction: (layout: Layout, item: LayoutItem, kind: DashboardInteractionKind) => void
    finishInteraction: () => void
}

export function useDashboardLayoutInteraction({
    layoutEditMode,
    layoutCompaction,
    updateLayouts,
}: UseDashboardLayoutInteractionProps): DashboardLayoutInteraction {
    const interactionInProgress = useRef(false)
    const pendingLayouts = useRef<Partial<Record<DashboardLayoutSize, Layout>> | null>(null)
    const baselineLayout = useRef<Layout | null>(null)
    const baselineById = useRef<Map<string, LayoutItem>>(new Map())
    const resizeNeighbors = useRef<ResizeNeighbors>({})
    const activeItemId = useRef<string | null>(null)
    const interactionKind = useRef<DashboardInteractionKind | null>(null)

    const gridCompactor = useMemo<Compactor>(() => {
        const compactor = getDashboardGridCompactor(layoutCompaction ?? DashboardGridCompaction.Vertical)

        return {
            ...compactor,
            compact: (layout: Layout, cols: number): Layout => {
                const baseline = baselineLayout.current
                const activeTileId = activeItemId.current
                if (!baseline || !activeTileId) {
                    return compactor.compact(layout, cols)
                }

                const kind = interactionKind.current ?? 'drag'
                // A resize leaves react-grid-layout's push in place for the tiles it overlaps, because the row
                // has to give way. A drag instead holds every other tile at its pre-drag position, so the tiles
                // the drag passes over stay where the user put them.
                const restoredLayout =
                    kind === 'resize'
                        ? restoreUnmovedItemPositions(layout, baseline, activeTileId, baselineById.current)
                        : pinUnmovedItemsToBaseline(layout, baseline, activeTileId, baselineById.current)
                const resizedLayout =
                    kind === 'resize'
                        ? resizeNeighborToFitRow(restoredLayout, baseline, activeTileId, resizeNeighbors.current)
                        : restoredLayout
                return compactor.compactInteraction(cols, activeTileId, kind, restoredLayout, resizedLayout)
            },
        }
    }, [layoutCompaction])

    const handleLayoutChange = useCallback(
        (_: unknown, newLayouts: Partial<Record<DashboardLayoutSize, Layout>>) => {
            if (!layoutEditMode) {
                return
            }
            if (interactionInProgress.current) {
                pendingLayouts.current = newLayouts
                return
            }
            updateLayouts(newLayouts)
        },
        [layoutEditMode, updateLayouts]
    )

    const startInteraction = useCallback((layout: Layout, item: LayoutItem, kind: DashboardInteractionKind): void => {
        interactionInProgress.current = true
        baselineLayout.current = layout.map((layoutItem) => cloneLayoutItem(layoutItem))
        baselineById.current = new Map(baselineLayout.current.map((layoutItem) => [layoutItem.i, layoutItem]))
        activeItemId.current = item.i
        interactionKind.current = kind
        resizeNeighbors.current = kind === 'resize' ? getResizeNeighbors(baselineLayout.current, item, item.i) : {}
    }, [])

    const finishInteraction = useCallback((): void => {
        interactionInProgress.current = false
        if (pendingLayouts.current) {
            updateLayouts(pendingLayouts.current)
            pendingLayouts.current = null
        }
        baselineLayout.current = null
        baselineById.current = new Map()
        resizeNeighbors.current = {}
        activeItemId.current = null
        interactionKind.current = null
    }, [updateLayouts])

    return { gridCompactor, handleLayoutChange, interactionInProgress, startInteraction, finishInteraction }
}
