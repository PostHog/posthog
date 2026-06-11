import React, { useCallback, useMemo } from 'react'

import type { ChartTheme, ResolvedSeries, Series } from './types'

// Literal class strings (no runtime concat) so Tailwind v4's `dist/*.js`
// source scan can see every utility — see the package's tailwind contract.
const WRAPPER_CLASS = 'relative w-full flex-1 min-h-0 overflow-hidden'
const STATIC_CANVAS_CLASS = 'absolute top-0 left-0'
const OVERLAY_CANVAS_CLASS = 'absolute top-0 left-0 pointer-events-none'
const OVERLAY_CLASS = 'absolute top-0 left-0 w-full h-full pointer-events-none'

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
    /** Show the pointer cursor — the hovered element is clickable. */
    pointer: boolean
    ariaLabel: string
    handlers: Required<Pick<React.DOMAttributes<HTMLDivElement>, 'onMouseMove' | 'onMouseLeave' | 'onClick'>>
    /** Render the overlay layer — bases gate this on layout readiness (dimensions + scales). */
    showOverlay: boolean
    children?: React.ReactNode
}

/** Shared DOM shell of the chart bases — behavior (interaction, drawing, contexts) stays in the bases. */
export function ChartShell({
    wrapperRef,
    canvasRef,
    overlayCanvasRef,
    className,
    dataAttr,
    pointer,
    ariaLabel,
    handlers,
    showOverlay,
    children,
}: ChartShellProps): React.ReactElement {
    return (
        <div
            ref={wrapperRef}
            className={[WRAPPER_CLASS, pointer ? 'cursor-pointer' : 'cursor-default', className]
                .filter(Boolean)
                .join(' ')}
            data-attr={dataAttr}
            onMouseMove={handlers.onMouseMove}
            onMouseLeave={handlers.onMouseLeave}
            onClick={handlers.onClick}
        >
            <canvas ref={canvasRef} role="img" aria-label={ariaLabel} className={STATIC_CANVAS_CLASS} />
            <canvas ref={overlayCanvasRef} aria-hidden="true" className={OVERLAY_CANVAS_CLASS} />

            {showOverlay && <div className={OVERLAY_CLASS}>{children}</div>}
        </div>
    )
}
