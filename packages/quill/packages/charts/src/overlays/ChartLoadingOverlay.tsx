/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from chart layout */
import React, { useEffect, useRef } from 'react'

import { useChartLayout } from '../core/chart-context'

const SWEEP_DURATION_MS = 1600
const SWEEP_WIDTH_RATIO = 0.45
const DEFAULT_HIGHLIGHT = 'rgba(255, 255, 255, 0.3)'

// Literal class strings (no runtime concat) so Tailwind v4's `dist/*.js`
// source scan can see every utility — see the package's tailwind contract.
const PLOT_CLIP_CLASS = 'absolute overflow-hidden'
const BAND_CLASS = 'absolute top-0 bottom-0'
const SLOT_CLASS = 'absolute inset-0 flex items-center justify-center pointer-events-auto'

export interface ChartLoadingOverlayProps {
    /** Gradient highlight of the sweeping band. Defaults to a soft white sheen. */
    highlightColor?: string
    /** Host content (progress message, cancel affordance) centered over the plot. */
    children?: React.ReactNode
}

/** Animated shimmer sweep across the plot area while a chart is loading or refreshing.
 *  Composes as a chart child; positions itself from the chart layout context. Honors
 *  `prefers-reduced-motion` (band stays hidden off-plot instead of sweeping). */
export function ChartLoadingOverlay({
    highlightColor = DEFAULT_HIGHLIGHT,
    children,
}: ChartLoadingOverlayProps): React.ReactElement {
    const { dimensions } = useChartLayout()
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
            { duration: SWEEP_DURATION_MS, iterations: Infinity, easing: 'ease-in-out' }
        )
        return () => animation.cancel()
    }, [plotWidth])

    return (
        <div
            data-attr="hog-chart-loading-overlay"
            className={PLOT_CLIP_CLASS}
            style={{ left: plotLeft, top: plotTop, width: plotWidth, height: plotHeight }}
        >
            <div
                ref={bandRef}
                className={BAND_CLASS}
                style={{
                    width: `${SWEEP_WIDTH_RATIO * 100}%`,
                    transform: 'translateX(-101%)',
                    background: `linear-gradient(90deg, transparent, ${highlightColor}, transparent)`,
                }}
            />
            {children != null && <div className={SLOT_CLASS}>{children}</div>}
        </div>
    )
}
