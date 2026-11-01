import { useCallback, useMemo, useRef } from 'react'
import type { MutableRefObject } from 'react'
import { cloneLayoutItem } from 'react-grid-layout'
import type { Compactor, Layout, LayoutItem } from 'react-grid-layout'

import {
    getResizeNeighbors,
    resizeNeighborToFitRow,
    restoreUnmovedItemPositions,
} from 'scenes/dashboard/dashboardResizeCompactor'
import type { ResizeNeighbors } from 'scenes/dashboard/dashboardResizeCompactor'

import type { DashboardLayoutSize } from '~/types'

import { DashboardGridCompaction, getDashboardGridCompactor } from 'products/dashboards/frontend/dashboardCustomization'

type InteractionKind = 'drag' | 'resize'

interface UseDashboardLayoutInteractionProps {
    /** Whether the viewer can move and resize tiles. */
    enabled: boolean
    layoutCompaction?: DashboardGridCompaction
    updateLayouts: (layouts: Partial<Record<DashboardLayoutSize, Layout>>) => void
}

interface DashboardLayoutInteraction {
    gridCompactor: Compactor
    handleLayoutChange: (_: unknown, newLayouts: Partial<Record<DashboardLayoutSize, Layout>>) => void
    interactionInProgress: MutableRefObject<boolean>
    startInteraction: (layout: Layout, item: LayoutItem, kind: InteractionKind) => void
    finishInteraction: () => void
}

export function useDashboardLayoutInteraction({
    enabled,
    layoutCompaction,
    updateLayouts,
}: UseDashboardLayoutInteractionProps): DashboardLayoutInteraction {
    const interactionInProgress = useRef(false)
    // The grid also reports layouts it works out itself (on mount, or as tiles stream in). Only a layout from
    // a drag or resize is the viewer's change, and the grid reports that one right after the gesture stops.
    const acceptingGestureLayout = useRef(false)
    const pendingLayouts = useRef<Partial<Record<DashboardLayoutSize, Layout>> | null>(null)
    const baselineLayout = useRef<Layout | null>(null)
    const baselineById = useRef<Map<string, LayoutItem>>(new Map())
    const resizeNeighbors = useRef<ResizeNeighbors>({})
    const activeItemId = useRef<string | null>(null)
    const interactionKind = useRef<InteractionKind | null>(null)

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

                const restoredLayout = restoreUnmovedItemPositions(
                    layout,
                    baseline,
                    activeTileId,
                    baselineById.current,
                    layoutCompaction === DashboardGridCompaction.Stable && interactionKind.current === 'drag'
                )
                const resizedLayout =
                    interactionKind.current === 'resize'
                        ? resizeNeighborToFitRow(restoredLayout, baseline, activeTileId, resizeNeighbors.current)
                        : restoredLayout
                return compactor.compactInteraction(
                    cols,
                    activeTileId,
                    restoredLayout,
                    resizedLayout,
                    interactionKind.current === 'drag'
                )
            },
        }
    }, [layoutCompaction])

    const handleLayoutChange = useCallback(
        (_: unknown, newLayouts: Partial<Record<DashboardLayoutSize, Layout>>) => {
            if (!enabled) {
                return
            }
            if (interactionInProgress.current) {
                pendingLayouts.current = newLayouts
                return
            }
            if (acceptingGestureLayout.current) {
                updateLayouts(newLayouts)
            }
        },
        [enabled, updateLayouts]
    )

    const startInteraction = useCallback((layout: Layout, item: LayoutItem, kind: InteractionKind): void => {
        interactionInProgress.current = true
        baselineLayout.current = layout.map((layoutItem) => cloneLayoutItem(layoutItem))
        baselineById.current = new Map(baselineLayout.current.map((layoutItem) => [layoutItem.i, layoutItem]))
        activeItemId.current = item.i
        interactionKind.current = kind
        resizeNeighbors.current = kind === 'resize' ? getResizeNeighbors(baselineLayout.current, item, item.i) : {}
    }, [])

    const finishInteraction = useCallback((): void => {
        interactionInProgress.current = false
        acceptingGestureLayout.current = true
        setTimeout(() => {
            acceptingGestureLayout.current = false
        }, 0)
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
