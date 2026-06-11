import React, { useCallback, useMemo } from 'react'

import type { ChartTheme, ResolvedSeries, Series } from './types'

const WRAPPER_STYLE_BASE: React.CSSProperties = {
    position: 'relative',
    width: '100%',
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
}
const WRAPPER_STYLE_DEFAULT: React.CSSProperties = { ...WRAPPER_STYLE_BASE, cursor: 'default' }
const WRAPPER_STYLE_POINTER: React.CSSProperties = { ...WRAPPER_STYLE_BASE, cursor: 'pointer' }

const STATIC_CANVAS_STYLE: React.CSSProperties = { position: 'absolute', top: 0, left: 0 }
const OVERLAY_CANVAS_STYLE: React.CSSProperties = { ...STATIC_CANVAS_STYLE, pointerEvents: 'none' }
const OVERLAY_STYLE: React.CSSProperties = { ...OVERLAY_CANVAS_STYLE, width: '100%', height: '100%' }

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
            className={className}
            data-attr={dataAttr}
            style={pointer ? WRAPPER_STYLE_POINTER : WRAPPER_STYLE_DEFAULT}
            onMouseMove={handlers.onMouseMove}
            onMouseLeave={handlers.onMouseLeave}
            onClick={handlers.onClick}
        >
            <canvas ref={canvasRef} role="img" aria-label={ariaLabel} style={STATIC_CANVAS_STYLE} />
            <canvas ref={overlayCanvasRef} aria-hidden="true" style={OVERLAY_CANVAS_STYLE} />

            {showOverlay && <div style={OVERLAY_STYLE}>{children}</div>}
        </div>
    )
}
