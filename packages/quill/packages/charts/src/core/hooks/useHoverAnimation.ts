import { useCallback, useEffect, useRef } from 'react'

import { monotonicNow } from '../time'
import type {
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    DragRect,
    DrawHoverResult,
    ResolvedSeries,
} from '../types'
import { clearAndPrepare } from './clearCanvas'
import { useCommittedRef } from './useLatest'

/** A hover index this chart mirrors from elsewhere (a `ChartGroup`), read outside React state so a
 *  change repaints the hover canvas without re-rendering the chart. */
export interface ExternalHoverSource {
    subscribe: (onChange: () => void) => () => void
    /** The mirrored index into this chart's labels, or -1 for none. */
    getIndex: () => number
}

const GROUP_HOVER_ATTRIBUTE = 'data-hog-charts-group-hover-index'

interface UseHoverAnimationOptions {
    /** Context for the hover overlay (highlight rings). Redrawn on every hoverIndex change. */
    overlayCtx: CanvasRenderingContext2D | null
    dimensions: ChartDimensions | null
    scales: ChartScales | null
    series: ResolvedSeries[]
    labels: string[]
    hoverIndex: number
    hoverPosition: { x: number; y: number } | null
    theme: ChartTheme
    dragRect?: DragRect | null
    drawHover: (args: ChartDrawArgs) => DrawHoverResult
    /** Duration (ms) of the hover-overlay fade-in. `0` snaps instantly. */
    hoverAnimationMs: number
    /** Drawn while the pointer is not over this chart. The local hover always wins. */
    externalHover?: ExternalHoverSource | null
}

/**
 * Drives the hover overlay's fade-in on its own RAF loop. The highlight eases in (progress 0→1)
 * when the cursor enters a band and cross-fades when it moves between bands. The overlay clears
 * when the cursor leaves (hoverIndex < 0).
 */
export function useHoverAnimation({
    overlayCtx,
    dimensions,
    scales,
    series,
    labels,
    hoverIndex,
    hoverPosition,
    theme,
    dragRect = null,
    drawHover,
    hoverAnimationMs,
    externalHover = null,
}: UseHoverAnimationOptions): void {
    // Cancel the prior RAF on re-run — relying on cleanup ordering alone leaves a
    // window where a stale RAF can paint after the new setup runs.
    const hoverRafRef = useRef<number | null>(null)
    const hoverAnimRef = useRef<{ idx: number; startTime: number }>({ idx: -1, startTime: 0 })
    // Freezes the fade timer while invisible (cursor in a band gap) so the fade always
    // starts at progress 0 when something visible first appears.
    const drewVisibleRef = useRef(false)
    // Mirror everything that changes per-mousemove so the paint routine stays stable —
    // otherwise we'd tear down and re-arm the RAF every mouse pixel. Committed refs, because a group
    // hover calls `schedule` from another chart's commit, outside this chart's render.
    const drawHoverRef = useCommittedRef(drawHover)
    const hoverPositionRef = useCommittedRef(hoverPosition)
    const seriesRef = useCommittedRef(series)
    const labelsRef = useCommittedRef(labels)
    const themeRef = useCommittedRef(theme)
    const dragRectRef = useCommittedRef(dragRect)
    const overlayCtxRef = useCommittedRef(overlayCtx)
    const dimensionsRef = useCommittedRef(dimensions)
    const scalesRef = useCommittedRef(scales)
    const localIndexRef = useCommittedRef(hoverIndex)
    const hoverAnimationMsRef = useCommittedRef(hoverAnimationMs)
    const externalHoverRef = useCommittedRef(externalHover)
    // The group index last written to the canvas attribute, so a repaint only touches the DOM on change.
    const groupAttributeRef = useRef(-1)

    const cancel = useCallback((): void => {
        if (hoverRafRef.current != null) {
            cancelAnimationFrame(hoverRafRef.current)
            hoverRafRef.current = null
        }
    }, [])

    // The RAF loop ticks until hoverProgress reaches 1, then exits and waits for the next
    // change. Timer is held in a ref so cancel/restart cycles resume the fade smoothly.
    const schedule = useCallback((): void => {
        cancel()
        const overlayCtx = overlayCtxRef.current
        const dimensions = dimensionsRef.current
        const scales = scalesRef.current
        const localIndex = localIndexRef.current
        const hoverAnimationMs = hoverAnimationMsRef.current
        if (!overlayCtx || !dimensions || !scales || themeRef.current.skipDraw) {
            return
        }
        const groupIndex = localIndex < 0 ? (externalHoverRef.current?.getIndex() ?? -1) : -1
        const hoverIndex = localIndex >= 0 ? localIndex : groupIndex
        const hoverSource = groupIndex >= 0 ? 'group' : 'pointer'
        if (groupIndex !== groupAttributeRef.current) {
            groupAttributeRef.current = groupIndex
            if (groupIndex >= 0) {
                overlayCtx.canvas.setAttribute(GROUP_HOVER_ATTRIBUTE, String(groupIndex))
            } else {
                overlayCtx.canvas.removeAttribute(GROUP_HOVER_ATTRIBUTE)
            }
        }
        // Restart the fade on hoverIndex change — invalidate drewVisible too so the next
        // visible frame starts at progress 0, not where the previous bar's fade left off.
        if (hoverIndex !== hoverAnimRef.current.idx) {
            hoverAnimRef.current.idx = hoverIndex
            hoverAnimRef.current.startTime = monotonicNow()
            drewVisibleRef.current = false
        }
        const resetHoverFade = (): number => {
            hoverAnimRef.current.startTime = monotonicNow()
            return 0
        }
        const tick = (): void => {
            // Pin progress to 0 while invisible — see drewVisibleRef comment above.
            if (!drewVisibleRef.current) {
                hoverAnimRef.current.startTime = monotonicNow()
            }
            const elapsed = monotonicNow() - hoverAnimRef.current.startTime
            const hoverProgress = hoverAnimationMs > 0 ? Math.min(1, elapsed / hoverAnimationMs) : 1
            clearAndPrepare(overlayCtx, dimensions)
            let drewVisible: DrawHoverResult
            try {
                drewVisible = drawHoverRef.current({
                    ctx: overlayCtx,
                    dimensions,
                    scales,
                    series: seriesRef.current,
                    labels: labelsRef.current,
                    hoverIndex,
                    hoverPosition: groupIndex >= 0 ? null : hoverPositionRef.current,
                    hoverSource,
                    theme: themeRef.current,
                    hoverProgress,
                    resetHoverFade,
                    dragRect: dragRectRef.current,
                })
            } finally {
                overlayCtx.restore()
            }
            drewVisibleRef.current = drewVisible
            // Recompute after the draw — the chart type may have called resetHoverFade
            // mid-draw, which would leave the cached hoverProgress stale.
            const liveElapsed = monotonicNow() - hoverAnimRef.current.startTime
            const liveProgress = hoverAnimationMs > 0 ? Math.min(1, liveElapsed / hoverAnimationMs) : 1
            if (drewVisible && liveProgress < 1 && hoverIndex >= 0) {
                hoverRafRef.current = requestAnimationFrame(tick)
            } else {
                hoverRafRef.current = null
            }
        }
        hoverRafRef.current = requestAnimationFrame(tick)
    }, [
        cancel,
        overlayCtxRef,
        dimensionsRef,
        scalesRef,
        localIndexRef,
        hoverAnimationMsRef,
        themeRef,
        externalHoverRef,
        drawHoverRef,
        seriesRef,
        labelsRef,
        hoverPositionRef,
        dragRectRef,
    ])

    useEffect(() => {
        schedule()
        return cancel
        // hoverPosition is in the dep array (not the ref) so the overlay redraws when the
        // cursor moves *within* the same band — bar charts decide on a hit per-frame in
        // `drawHover`, and entering a bar from canvas-empty-space doesn't change hoverIndex.
        // The fade timer only resets on hoverIndex change (see schedule), so re-running
        // per mousemove doesn't restart the animation.
        // series/labels/theme/drawHover/dragRect are read via refs — dragRect is also in the dep
        // array below so the overlay repaints the selection as the drag rectangle changes.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [overlayCtx, dimensions, scales, hoverIndex, hoverPosition, hoverAnimationMs, dragRect, externalHover])

    useEffect(() => {
        if (!externalHover) {
            return
        }
        let lastIndex = externalHover.getIndex()
        return externalHover.subscribe(() => {
            const index = externalHover.getIndex()
            if (index === lastIndex) {
                return
            }
            lastIndex = index
            if (localIndexRef.current < 0) {
                schedule()
            }
        })
    }, [externalHover, schedule, localIndexRef])
}
