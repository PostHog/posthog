import React, { useCallback, useMemo } from 'react'

import type { ChartTheme, ResolvedSeries, Series } from './types'

// Literal class strings (no runtime concat) so Tailwind v4's `dist/*.js`
// source scan can see every utility — see the package's tailwind contract.
const WRAPPER_CLASS = 'w-full flex-1'

// Containment is a presentation style, not a utility class, because it has to hold with no CSS at
// all. An in-flow canvas grows the wrapper, the wrapper's `ResizeObserver` measures the taller
// wrapper, and the canvas grows again — a loop that runs to the browser's maximum element height
// and paints the chart over the whole page. Taking the layers out of flow breaks that loop, so it
// cannot depend on a stylesheet that may still be loading.
const WRAPPER_STYLE: React.CSSProperties = { position: 'relative', minHeight: 0, overflow: 'hidden' }
const LAYER_STYLE: React.CSSProperties = { position: 'absolute', top: 0, left: 0 }
const PASSIVE_LAYER_STYLE: React.CSSProperties = { ...LAYER_STYLE, pointerEvents: 'none' }
const OVERLAY_STYLE: React.CSSProperties = { ...PASSIVE_LAYER_STYLE, width: '100%', height: '100%' }

/** Applies the theme's color fallback to series missing an explicit `color`. */
export function useColoredSeries<Meta = unknown>(series: Series<Meta>[], theme: ChartTheme): ResolvedSeries<Meta>[] {
    return useMemo<ResolvedSeries<Meta>[]>(
        () =>
            series.map((s, i) => ({
                ...s,
                color: s.color || theme.colors[i % theme.colors.length],
            })),
        [series, theme.colors]
    )
}

export function useCanvasBounds(canvasRef: React.RefObject<HTMLCanvasElement>): () => DOMRect | null {
    return useCallback((): DOMRect | null => canvasRef.current?.getBoundingClientRect() ?? null, [canvasRef])
}

export const countVisibleSeries = (series: ResolvedSeries[]): number =>
    series.reduce((n, s) => n + (s.visibility?.excluded ? 0 : 1), 0)

export interface ChartShellProps {
    wrapperRef: React.RefObject<HTMLDivElement>
    canvasRef: React.RefObject<HTMLCanvasElement>
    overlayCanvasRef: React.RefObject<HTMLCanvasElement>
    className?: string
    dataAttr?: string
    /** Show the pointer cursor — the hovered element is clickable. Takes precedence over `crosshair`. */
    pointer: boolean
    /** Show the crosshair cursor — a drag gesture (e.g. drag-to-zoom) is available. */
    crosshair?: boolean
    ariaLabel: string
    handlers: Required<Pick<React.DOMAttributes<HTMLDivElement>, 'onMouseMove' | 'onMouseLeave' | 'onClick'>> &
        Pick<React.DOMAttributes<HTMLDivElement>, 'onMouseDown' | 'onPointerDown'>
    /** Render the overlay layer — bases gate this on layout readiness (dimensions + scales). */
    showOverlay: boolean
    children?: React.ReactNode
}

// Literal cursor classes (no runtime concat) so Tailwind v4's source scan sees them — see the package's tailwind contract.
function cursorClass(pointer: boolean, crosshair: boolean): string {
    if (pointer) {
        return 'cursor-pointer'
    }
    if (crosshair) {
        return 'cursor-crosshair'
    }
    return 'cursor-default'
}

/** Shared DOM shell of the chart bases — behavior (interaction, drawing, contexts) stays in the bases. */
export function ChartShell({
    wrapperRef,
    canvasRef,
    overlayCanvasRef,
    className,
    dataAttr,
    pointer,
    crosshair = false,
    ariaLabel,
    handlers,
    showOverlay,
    children,
}: ChartShellProps): React.ReactElement {
    return (
        <div
            ref={wrapperRef}
            className={[WRAPPER_CLASS, cursorClass(pointer, crosshair), className].filter(Boolean).join(' ')}
            style={WRAPPER_STYLE}
            data-attr={dataAttr}
            onMouseDown={handlers.onMouseDown}
            onMouseMove={handlers.onMouseMove}
            onMouseLeave={handlers.onMouseLeave}
            onClick={handlers.onClick}
            onPointerDown={handlers.onPointerDown}
        >
            <canvas ref={canvasRef} role="img" aria-label={ariaLabel} style={LAYER_STYLE} />
            <canvas ref={overlayCanvasRef} aria-hidden="true" style={PASSIVE_LAYER_STYLE} />

            {showOverlay && <div style={OVERLAY_STYLE}>{children}</div>}
        </div>
    )
}
