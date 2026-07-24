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

/** Accessor for the built-in `DefaultTooltip` layout, reading its stable `data-attr`
 *  test hooks. Use when a chart renders `DefaultTooltip` (directly or via a custom
 *  `tooltip` render prop that wraps it). */
export interface DefaultTooltipAccessor extends HogChartTooltip {
    /** Header label — typically the hovered x-axis value. */
    label(): string
    /** Series labels in render order (excludes the total row). */
    rows(): string[]
    /** Formatted value for the series row whose label matches, or undefined. */
    value(seriesLabel: string): string | undefined
    /** Series swatch colors (inline `background-color`) in row order. */
    swatchColors(): string[]
    /** Formatted total-row value, or undefined when no total row is shown. */
    total(): string | undefined
}

const seriesLabelOf = (row: HTMLElement): string =>
    (row.querySelector('[data-attr="hog-chart-tooltip-series"]')?.textContent ?? '').replace(/:\s*$/, '').trim()

const swatchColorOf = (row: HTMLElement): string =>
    row.querySelector<HTMLElement>('[data-attr="hog-chart-tooltip-swatch"]')?.style.backgroundColor ?? ''

export function createDefaultTooltipAccessor(element: HTMLElement): DefaultTooltipAccessor {
    const rowEls = (): HTMLElement[] =>
        Array.from(element.querySelectorAll<HTMLElement>('[data-attr="hog-chart-tooltip-row"]'))

    return Object.assign(createHogChartTooltip(element), {
        label(): string {
            return element.querySelector('[data-attr="hog-chart-tooltip-label"]')?.textContent?.trim() ?? ''
        },
        rows(): string[] {
            return rowEls().map(seriesLabelOf)
        },
        value(seriesLabel: string): string | undefined {
            const row = rowEls().find((r) => seriesLabelOf(r) === seriesLabel)
            return row?.querySelector('[data-attr="hog-chart-tooltip-value"]')?.textContent ?? undefined
        },
        swatchColors(): string[] {
            return rowEls().map(swatchColorOf)
        },
        total(): string | undefined {
            const total = element.querySelector('[data-attr="hog-chart-tooltip-total"]')
            return total?.querySelector('[data-attr="hog-chart-tooltip-value"]')?.textContent ?? undefined
        },
    })
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
