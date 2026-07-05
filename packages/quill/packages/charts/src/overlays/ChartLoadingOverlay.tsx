/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from chart layout */
import React, { useEffect, useRef } from 'react'

import { useChartLayout } from '../core/chart-context'

const SWEEP_DURATION_MS = 1400
const SWEEP_WIDTH_RATIO = 0.35
const SWEEP_OPACITY = 0.95
const DEFAULT_VEIL_COLOR = '#ffffff'
/** Keeps the sweep off the L-axis baselines at the plot's left/bottom edges, so the axes
 *  hold steady while the marks shimmer. */
const AXIS_INSET_PX = 3

// Literal class strings (no runtime concat) so Tailwind v4's `dist/*.js`
// source scan can see every utility — see the package's tailwind contract.
const PLOT_CLIP_CLASS = 'absolute overflow-hidden'
const BAND_CLASS = 'absolute top-0 bottom-0'
const SLOT_CLASS = 'absolute inset-0 flex items-center justify-center pointer-events-auto'

export interface ChartLoadingOverlayProps {
    /** Host content (progress message, cancel affordance) centered over the plot. */
    children?: React.ReactNode
}

/** Classic skeleton shimmer over the plot area while a chart is loading or refreshing:
 *  a background-colored gradient band sweeps left-to-right, dimming the marks as it
 *  passes. Works on any surface (a highlight band would vanish on same-colored
 *  backgrounds). Composes as a chart child; positions from the chart layout context.
 *  Static under `prefers-reduced-motion` and automated browsers. */
export function ChartLoadingOverlay({ children }: ChartLoadingOverlayProps): React.ReactElement {
    const { dimensions, theme } = useChartLayout()
    const bandRef = useRef<HTMLDivElement>(null)
    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions

    useEffect(() => {
        const band = bandRef.current
        // Web Animations API keeps the package free of shipped CSS keyframes; jsdom lacks it.
        if (!band || typeof band.animate !== 'function') {
            return
        }
        if (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return
        }
        // Automated browsers (visual-regression snapshots) get a static band — a mid-sweep
        // screenshot would differ every run.
        if (typeof navigator !== 'undefined' && navigator.webdriver) {
            return
        }
        const bandWidth = plotWidth * SWEEP_WIDTH_RATIO
        const animation = band.animate(
            [{ transform: `translateX(${-bandWidth}px)` }, { transform: `translateX(${plotWidth}px)` }],
            { duration: SWEEP_DURATION_MS, iterations: Infinity, easing: 'linear' }
        )
        return () => animation.cancel()
    }, [plotWidth])

    const veilColor = theme.backgroundColor ?? DEFAULT_VEIL_COLOR

    return (
        <div
            data-attr="hog-chart-loading-overlay"
            className={PLOT_CLIP_CLASS}
            style={{
                left: plotLeft + AXIS_INSET_PX,
                top: plotTop,
                width: plotWidth - AXIS_INSET_PX,
                height: plotHeight - AXIS_INSET_PX,
            }}
        >
            <div
                ref={bandRef}
                className={BAND_CLASS}
                style={{
                    width: `${SWEEP_WIDTH_RATIO * 100}%`,
                    transform: 'translateX(-101%)',
                    background: `linear-gradient(90deg, transparent, ${veilColor}, transparent)`,
                    opacity: SWEEP_OPACITY,
                }}
            />
            {children != null && <div className={SLOT_CLASS}>{children}</div>}
        </div>
    )
}
