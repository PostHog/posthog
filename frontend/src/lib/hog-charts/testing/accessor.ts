// DOM-based inspector for hog-charts. Reads what the chart rendered so tests
// can assert on overlays (value labels, reference lines, axis ticks) and the
// reported series count without poking at the canvas.
//
// The data-attr selectors below are part of the library's stable testing
// contract — renaming them breaks consumers' tests. Keep in sync with the
// overlay components that emit them.

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

export interface HogChart {
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
    /** Annotation badges currently rendered. */
    annotationBadges(): HTMLElement[]
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

export function getHogChart(scope: HTMLElement = document.body): HogChart {
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
        annotationBadges: () => Array.from(wrapper.querySelectorAll<HTMLElement>('.AnnotationsBadge')),
    }
}
