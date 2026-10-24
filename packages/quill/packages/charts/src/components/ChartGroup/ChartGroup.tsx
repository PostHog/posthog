import React, { useCallback, useEffect, useLayoutEffect, useMemo, useState } from 'react'

import type { ChartGroupRange } from '../../core/chart-group'
import {
    ChartGroupContext,
    type ChartGroupContextValue,
    type ChartGroupTooltipMode,
} from '../../core/chart-group-context'
import { createChartGroupStore } from '../../core/chart-group-store'
import { useLatest } from '../../core/hooks/useLatest'

export interface ChartGroupProps {
    children: React.ReactNode
    /** Hovering one chart draws a crosshair and hover highlight at the same x on every other chart.
     *  Defaults to true. */
    syncCrosshair?: boolean
    /** `hovered` (default) shows a tooltip only on the chart under the pointer. `all` also shows
     *  each other chart's tooltip at the matching x, which re-renders and positions one tooltip per
     *  chart for each hovered label. */
    syncTooltip?: ChartGroupTooltipMode
    /** Turns on drag-to-zoom for every time chart in the group, and fires once with the dragged
     *  range, whichever chart the drag was on. The group does not zoom anything itself: update the range
     *  you pass to the charts. A chart's own `onDateRangeZoom` still fires too. */
    onZoom?: (range: ChartGroupRange) => void
    /** Shows a brush selection (the Heatmap's `onBrush`) as a highlighted range on every chart in
     *  the group. Defaults to true. */
    syncSelection?: boolean
    /** The shared selection, for a parent that owns it. Leave undefined to let the group keep the
     *  last brush itself, until Escape clears it. Pass null for no selection. */
    selection?: ChartGroupRange | null
    /** Fired when a brush in any chart selects a range, and with null when Escape clears it. */
    onSelectionChange?: (selection: ChartGroupRange | null) => void
}

/** Links the charts inside it so they share hover, crosshair, tooltip, zoom and selection. Charts
 *  join by being rendered anywhere inside, at any depth; a chart leaves with `syncWithGroup={false}`.
 *  Charts line up by x value, not by index: ISO time labels match by time, so hourly and 5-minute
 *  charts align, and other labels match by their exact string. Renders no DOM of its own. */
export function ChartGroup({
    children,
    syncCrosshair = true,
    syncTooltip = 'hovered',
    onZoom,
    syncSelection = true,
    selection,
    onSelectionChange,
}: ChartGroupProps): React.ReactElement {
    const [store] = useState(() => createChartGroupStore(selection ?? null))
    const onZoomRef = useLatest(onZoom)
    const onSelectionChangeRef = useLatest(onSelectionChange)
    const controlled = selection !== undefined
    const controlledRef = useLatest(controlled)

    useLayoutEffect(() => {
        if (controlled) {
            store.setSelection(selection)
        }
    }, [store, controlled, selection])

    const select = useCallback(
        (range: ChartGroupRange): void => {
            if (!controlledRef.current) {
                store.setSelection(range)
            }
            onSelectionChangeRef.current?.(range)
        },
        [store, controlledRef, onSelectionChangeRef]
    )

    useEffect(() => {
        if (!syncSelection) {
            return
        }
        const onKeyDown = (e: KeyboardEvent): void => {
            // A handler that already used this Escape (closing a modal or menu) marks it prevented, and
            // an open pinned tooltip takes the Escape before the selection does.
            if (
                e.key !== 'Escape' ||
                e.defaultPrevented ||
                !store.getSelection() ||
                document.querySelector('.hog-charts-tooltip--pinned')
            ) {
                return
            }
            if (!controlledRef.current) {
                store.setSelection(null)
            }
            onSelectionChangeRef.current?.(null)
        }
        document.addEventListener('keydown', onKeyDown)
        return () => document.removeEventListener('keydown', onKeyDown)
    }, [store, syncSelection, controlledRef, onSelectionChangeRef])

    const hasZoom = !!onZoom
    const zoom = useMemo(
        () => (hasZoom ? (range: ChartGroupRange): void => onZoomRef.current?.(range) : null),
        [hasZoom, onZoomRef]
    )

    const value = useMemo<ChartGroupContextValue>(
        () => ({ store, syncCrosshair, syncTooltip, syncSelection, zoom, select }),
        [store, syncCrosshair, syncTooltip, syncSelection, zoom, select]
    )

    return <ChartGroupContext.Provider value={value}>{children}</ChartGroupContext.Provider>
}
