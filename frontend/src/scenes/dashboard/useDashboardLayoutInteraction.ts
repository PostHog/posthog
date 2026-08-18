import { useCallback, useMemo, useRef } from 'react'
import type { MutableRefObject } from 'react'
import { cloneLayoutItem, verticalCompactor } from 'react-grid-layout'
import type { Compactor, Layout, LayoutItem } from 'react-grid-layout'

import {
    getResizeNeighbors,
    resizeNeighborToFitRow,
    restoreUnmovedItemPositions,
} from 'scenes/dashboard/dashboardResizeCompactor'
import type { ResizeNeighbors } from 'scenes/dashboard/dashboardResizeCompactor'

import type { DashboardLayoutSize } from '~/types'

type InteractionKind = 'drag' | 'resize'

interface UseDashboardLayoutInteractionProps {
    layoutEditMode: boolean
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
    layoutEditMode,
    updateLayouts,
}: UseDashboardLayoutInteractionProps): DashboardLayoutInteraction {
    const interactionInProgress = useRef(false)
    const pendingLayouts = useRef<Partial<Record<DashboardLayoutSize, Layout>> | null>(null)
    const baselineLayout = useRef<Layout | null>(null)
    const baselineById = useRef<Map<string, LayoutItem>>(new Map())
    const resizeNeighbors = useRef<ResizeNeighbors>({})
    const activeItemId = useRef<string | null>(null)
    const interactionKind = useRef<InteractionKind | null>(null)

    const gridCompactor = useMemo<Compactor>(
        () => ({
            ...verticalCompactor,
            compact: (layout: Layout, cols: number): Layout => {
                const baseline = baselineLayout.current
                const activeTileId = activeItemId.current
                if (!baseline || !activeTileId) {
                    return verticalCompactor.compact(layout, cols)
                }

                const restoredLayout = restoreUnmovedItemPositions(layout, baseline, activeTileId, baselineById.current)
                const layoutForCompaction =
                    interactionKind.current === 'resize'
                        ? resizeNeighborToFitRow(restoredLayout, baseline, activeTileId, resizeNeighbors.current)
                        : restoredLayout
                return verticalCompactor.compact(layoutForCompaction, cols)
            },
        }),
        []
    )

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
