import React, { useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'

import { Tooltip } from '../overlays/Tooltip'
import type { ExternalHoverSource } from './hooks/useHoverAnimation'
import type { ChartDimensions, TooltipConfig, TooltipContext } from './types'

const NO_INDEX = (): number => -1

interface ChartGroupTooltipProps<Meta> {
    source: ExternalHoverSource
    /** The chart's own hover index. A pointer over this chart wins over the group. */
    localHoverIndex: number
    buildTooltipCtx: (
        index: number,
        position: { x: number; y: number } | null,
        canvasBounds?: DOMRect
    ) => TooltipContext<Meta> | null
    renderTooltip: (ctx: TooltipContext<Meta>) => React.ReactNode
    placement: TooltipConfig['placement']
    /** Reads the canvas rect. Called on mount, resize and scroll only, never during render. */
    canvasBounds: () => DOMRect | null
    /** Changes when the chart resizes, which moves the canvas rect. */
    dimensions: ChartDimensions | null
}

/** The tooltip a chart shows for another chart's hover under `syncTooltip: 'all'`. Subscribes on its
 *  own, so a group hover re-renders this tooltip and not the chart around it. */
export function ChartGroupTooltip<Meta>({
    source,
    localHoverIndex,
    buildTooltipCtx,
    renderTooltip,
    placement,
    canvasBounds,
    dimensions,
}: ChartGroupTooltipProps<Meta>): React.ReactElement | null {
    const index = useSyncExternalStore(source.subscribe, source.getIndex, NO_INDEX)

    // Every chart in the group re-renders this on each hovered label, so the canvas rect is cached
    // here instead of forcing a layout read per chart per label.
    const [bounds, setBounds] = useState<DOMRect | null>(null)
    const canvasBoundsRef = useRef(canvasBounds)
    canvasBoundsRef.current = canvasBounds
    useLayoutEffect(() => {
        const measure = (): void => setBounds(canvasBoundsRef.current())
        measure()
        window.addEventListener('resize', measure, { passive: true })
        window.addEventListener('scroll', measure, { passive: true, capture: true })
        return () => {
            window.removeEventListener('resize', measure)
            window.removeEventListener('scroll', measure, true)
        }
    }, [dimensions])

    const content = useMemo(() => {
        const context = index >= 0 && localHoverIndex < 0 && bounds ? buildTooltipCtx(index, null, bounds) : null
        const rendered = context ? renderTooltip(context) : null
        return context && rendered != null ? { context, rendered } : null
    }, [index, localHoverIndex, bounds, buildTooltipCtx, renderTooltip])

    // A chart type can render nothing for a mirrored hover (the Heatmap has no cell under it), and
    // then no floating element should mount at all.
    if (!content) {
        return null
    }
    return <Tooltip context={content.context} renderTooltip={() => content.rendered} placement={placement} />
}
