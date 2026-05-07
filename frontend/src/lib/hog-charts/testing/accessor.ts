// DOM-based inspector for hog-charts. Reads what the chart rendered so tests
// can assert on overlays (value labels, reference lines, axis ticks) and the
// reported series count without poking at the canvas.
//
// The data-attr selectors below are part of the library's stable testing
// contract — renaming them breaks consumers' tests. Keep in sync with the
// overlay components that emit them.

import { fireEvent } from '@testing-library/react'

import type { TooltipContext } from '../core/types'
import { dimensions } from './jsdom'
import { type HogChartTooltip, waitForHogChartTooltip } from './tooltip'

/** Handle returned by `chart.waitForTooltip()` — every field of the structured `TooltipContext`,
 *  plus the rendered portal `element` and an `isPinned` snapshot. */
export type TooltipSnapshot<Meta = unknown> = TooltipContext<Meta> & HogChartTooltip

interface ReferenceLineSummary {
    label: string | null
    /** Pixel position of the line — top px for horizontal, left px for vertical. */
    position: number | null
    /** Line color from inline style. */
    color: string | null
    /** "horizontal" for top-anchored lines, "vertical" for left-anchored. */
    orientation: 'horizontal' | 'vertical' | null
}

interface ValueLabelSummary {
    text: string
    /** Inline style backgroundColor (matches the series color). */
    color: string
}

interface AnomalyPointSummary {
    element: HTMLElement
    /** Inline style backgroundColor (matches the marker's series color). */
    color: string
}

export interface HogChart<Meta = unknown> {
    /** The wrapper div of this chart. */
    element: HTMLElement
    /** Number of non-excluded data series rendered (read from the chart's aria-label). */
    seriesCount: number
    /** Visible y-axis tick labels (left axis). */
    yTicks(): string[]
    /** Visible right y-axis tick labels (multi-axis charts). */
    yRightTicks(): string[]
    /** Visible x-axis tick labels (post-collision-avoidance). */
    xTicks(): string[]
    /** Whether a right-y axis was rendered. */
    hasRightAxis: boolean
    /** All reference lines currently rendered for this chart (goal/alert/marker). */
    referenceLines(): ReferenceLineSummary[]
    /** All value-label overlays currently rendered for this chart. */
    valueLabels(): ValueLabelSummary[]
    /** All anomaly point markers currently rendered (TimeSeriesLineChart only). */
    anomalyPoints(): AnomalyPointSummary[]
    /** Annotation badges currently rendered. */
    annotationBadges(): HTMLElement[]
    /** Fire a `mouseMove` over the data point at `index`. Only available when the chart was
     *  rendered via `renderHogChart` (it reads label count from `ui.props.labels`); the
     *  module-level `hoverAtIndex(wrapper, index, totalLabels)` is the explicit alternative. */
    hoverAtIndex(index: number): void
    /** Hover at the index, wait for the tooltip to settle, then click. Mirrors the
     *  hover-then-click sequence the chart's onClick handler relies on. */
    clickAtIndex(index: number): Promise<void>
    /** Wait for the tooltip to mount, then return a snapshot — every `TooltipContext` field
     *  plus the rendered portal element and an `isPinned` getter. Only available when the
     *  chart was rendered via `renderHogChart`; throws otherwise. */
    waitForTooltip(timeout?: number): Promise<TooltipSnapshot<Meta>>
}

export interface GetHogChartOptions<Meta = unknown> {
    /** Returns the most recent `TooltipContext` the chart computed (set up by `renderHogChart`'s
     *  capturing tooltip wrapper). When omitted, `chart.waitForTooltip()` throws. */
    getLastTooltipContext?: () => TooltipContext<Meta> | null
    /** Total label count for `chart.hoverAtIndex` / `chart.clickAtIndex`. When omitted, those
     *  methods throw — use the module-level `hoverAtIndex` instead. */
    totalLabels?: number
}

const SERIES_COUNT_RE = /Chart with (\d+) data series/i

function findCanvas(scope: HTMLElement): HTMLCanvasElement | null {
    return scope.querySelector('canvas[aria-label]')
}

function parsePixelStyle(style: CSSStyleDeclaration, prop: 'top' | 'left'): number | null {
    const raw = style[prop]
    if (!raw || !raw.endsWith('px')) {
        return null
    }
    const n = Number(raw.slice(0, -2))
    return Number.isFinite(n) ? n : null
}

// The reference-line component renders a 1px line as a single coloured border
// edge on an otherwise zero-size div: horizontal lines colour `border-top`,
// vertical lines colour `border-left`. Whichever of the two is set tells us
// both the orientation and the line colour in one shot.
function readReferenceLine(el: HTMLElement): ReferenceLineSummary {
    const horizontalColor = el.style.borderTopColor
    const verticalColor = el.style.borderLeftColor
    const orientation: 'horizontal' | 'vertical' | null = horizontalColor
        ? 'horizontal'
        : verticalColor
          ? 'vertical'
          : null
    const color = horizontalColor || verticalColor || null
    const position = parsePixelStyle(el.style, orientation === 'vertical' ? 'left' : 'top')

    // The optional label is rendered as the immediately-following sibling div.
    const labelEl = el.nextElementSibling
    const isLabel = labelEl?.getAttribute('data-attr') === 'hog-chart-reference-line-label'
    const label = isLabel ? (labelEl as HTMLElement).textContent : null

    return { color, orientation, position, label }
}

function clientForIndex(totalLabels: number, index: number): { clientX: number; clientY: number } {
    const step = dimensions.plotWidth / Math.max(1, totalLabels - 1)
    return {
        clientX: dimensions.plotLeft + step * index,
        clientY: dimensions.plotTop + dimensions.plotHeight / 2,
    }
}

export function getHogChart<Meta = unknown>(
    scope: HTMLElement = document.body,
    options: GetHogChartOptions<Meta> = {}
): HogChart<Meta> {
    const canvas = findCanvas(scope)
    if (!canvas) {
        throw new Error('No hog-chart canvas found in scope')
    }
    // The chart wrapper is the canvas's parent — overlays render as siblings
    // of the canvas inside that wrapper.
    const wrapper = canvas.parentElement
    if (!wrapper) {
        throw new Error('hog-chart canvas has no parent wrapper')
    }

    const ariaLabel = canvas.getAttribute('aria-label') ?? ''
    const match = SERIES_COUNT_RE.exec(ariaLabel)
    const seriesCount = match ? Number(match[1]) : 0

    const { getLastTooltipContext, totalLabels } = options

    return {
        element: wrapper,
        seriesCount,
        get hasRightAxis(): boolean {
            return wrapper.querySelectorAll('[data-attr="hog-chart-axis-tick-yr"]').length > 0
        },
        yTicks: () =>
            Array.from(wrapper.querySelectorAll<HTMLElement>('[data-attr="hog-chart-axis-tick-y"]')).map(
                (el) => el.textContent ?? ''
            ),
        yRightTicks: () =>
            Array.from(wrapper.querySelectorAll<HTMLElement>('[data-attr="hog-chart-axis-tick-yr"]')).map(
                (el) => el.textContent ?? ''
            ),
        xTicks: () =>
            Array.from(wrapper.querySelectorAll<HTMLElement>('[data-attr="hog-chart-axis-tick-x"]')).map(
                (el) => el.textContent ?? ''
            ),
        referenceLines: () =>
            Array.from(wrapper.querySelectorAll<HTMLElement>('[data-attr="hog-chart-reference-line"]')).map(
                readReferenceLine
            ),
        valueLabels: () =>
            Array.from(wrapper.querySelectorAll<HTMLElement>('[data-attr="hog-chart-value-label"]')).map((el) => ({
                text: el.textContent ?? '',
                color: el.style.backgroundColor,
            })),
        anomalyPoints: () =>
            Array.from(wrapper.querySelectorAll<HTMLElement>('[data-attr="hog-chart-anomaly-point"]')).map((el) => ({
                element: el,
                color: el.style.backgroundColor,
            })),
        annotationBadges: () => Array.from(wrapper.querySelectorAll<HTMLElement>('.AnnotationsBadge')),
        hoverAtIndex(index: number): void {
            if (totalLabels === undefined) {
                throw new Error('chart.hoverAtIndex requires renderHogChart (which captures labels.length)')
            }
            fireEvent.mouseMove(wrapper, clientForIndex(totalLabels, index))
        },
        async clickAtIndex(index: number): Promise<void> {
            if (totalLabels === undefined) {
                throw new Error('chart.clickAtIndex requires renderHogChart (which captures labels.length)')
            }
            fireEvent.mouseMove(wrapper, clientForIndex(totalLabels, index))
            // Wait for the hover state to flush — the click handler reads live tooltipCtx
            // synchronously to choose between pinning and onPointClick.
            await waitForHogChartTooltip()
            fireEvent.click(wrapper)
        },
        async waitForTooltip(timeout?: number): Promise<TooltipSnapshot<Meta>> {
            const element = await waitForHogChartTooltip(timeout)
            const ctx = getLastTooltipContext?.() ?? null
            if (!ctx) {
                throw new Error(
                    'TooltipContext not captured. Render via renderHogChart to enable tooltip context capture.'
                )
            }
            return {
                ...ctx,
                element,
                isPinned: element.classList.contains('hog-charts-tooltip--pinned'),
            }
        },
    }
}
