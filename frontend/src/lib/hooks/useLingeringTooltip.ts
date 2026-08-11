import { useEffect, useState } from 'react'

/** How long the tooltip stays up after the chart stops reporting a hover, to let the pointer reach it. */
export const LINGERING_TOOLTIP_MS = 300

export interface LingeringTooltip {
    visible: boolean
    onMouseEnter: () => void
    onMouseLeave: () => void
}

/**
 * Keeps a chart's hover tooltip open long enough for the pointer to travel from the canvas onto the
 * tooltip itself, so one taller than its max height can be scrolled. Charting libraries hide the
 * tooltip the instant the pointer leaves the canvas — which is before it can ever reach the
 * tooltip — so without a grace period an interactive tooltip is unreachable.
 *
 * Pass the chart's own notion of tooltip visibility as `chartVisible`, and spread the returned
 * mouse handlers onto the tooltip overlay. While the pointer is over the overlay the tooltip is
 * held open indefinitely; once it leaves, the grace period runs again and then it hides.
 *
 * When `enabled` is false this is a pass-through, so callers can keep the default
 * non-interactive behaviour (an interactive tooltip overlays the canvas and swallows its clicks).
 */
export function useLingeringTooltip(chartVisible: boolean, enabled: boolean): LingeringTooltip {
    const [hovered, setHovered] = useState(false)
    const [lingering, setLingering] = useState(false)

    useEffect(() => {
        if (!enabled) {
            return
        }
        if (chartVisible) {
            setLingering(true)
            return
        }
        // Hold indefinitely while the pointer is on the tooltip; the timer restarts when it leaves.
        if (!lingering || hovered) {
            return
        }
        const timeout = setTimeout(() => setLingering(false), LINGERING_TOOLTIP_MS)
        return () => clearTimeout(timeout)
    }, [enabled, chartVisible, lingering, hovered])

    useEffect(() => {
        // Turning the behaviour off mid-hover would otherwise wedge the tooltip open forever.
        if (!enabled) {
            setHovered(false)
            setLingering(false)
        }
    }, [enabled])

    return {
        visible: enabled ? chartVisible || lingering || hovered : chartVisible,
        onMouseEnter: () => setHovered(true),
        onMouseLeave: () => setHovered(false),
    }
}
