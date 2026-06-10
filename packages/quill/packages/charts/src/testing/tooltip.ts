import { waitFor } from '@testing-library/react'

/** Stable selector for the chart tooltip portal — hog-charts renders this on
 *  the document root via FloatingPortal, so it can't be found inside the chart
 *  wrapper. Kept in sync with overlays/Tooltip.tsx. */
export const HOG_CHARTS_TOOLTIP_SELECTOR = '[data-hog-charts-tooltip]'

export interface HogChartTooltip {
    element: HTMLElement
    /** True once the user has clicked to pin the tooltip. Reflects the
     *  `hog-charts-tooltip--pinned` class set by overlays/Tooltip.tsx. */
    readonly isPinned: boolean
}

/** Generic tooltip accessor — exposes only the portal element and pinned
 *  state. Consumers with their own tooltip renderer (e.g. an InsightTooltip
 *  with a table layout) should layer their own DOM accessor on top of this. */
export function createHogChartTooltip(element: HTMLElement): HogChartTooltip {
    return {
        element,
        get isPinned(): boolean {
            return element.classList.contains('hog-charts-tooltip--pinned')
        },
    }
}

/** Currently rendered chart tooltip element, or null if none is mounted. */
export function getHogChartTooltip(): HTMLElement | null {
    return document.querySelector(HOG_CHARTS_TOOLTIP_SELECTOR)
}

/** Wait until a chart tooltip is present in the document and return it. `beforePoll`, if given,
 *  runs at the start of each poll attempt — used to re-dispatch a triggering event (e.g. a hover)
 *  that the chart may have dropped before it became interactive. */
export async function waitForHogChartTooltip(timeout = 3000, beforePoll?: () => void): Promise<HTMLElement> {
    // Flush pending microtasks so React portal commits complete before polling.
    await new Promise((r) => setTimeout(r, 0))

    let tooltip!: HTMLElement
    await waitFor(
        () => {
            beforePoll?.()
            const el = getHogChartTooltip()
            if (!el) {
                throw new Error('tooltip not yet rendered')
            }
            tooltip = el
        },
        { timeout, interval: 10 }
    )
    return tooltip
}
