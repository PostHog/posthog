/**
 * Shared chart infrastructure extracted from both LineGraph implementations.
 *
 * This file contains the 18 patterns that were duplicated across:
 * - scenes/insights/views/LineGraph/LineGraph.tsx (1,126 lines)
 * - queries/nodes/DataVisualization/Components/Charts/LineGraph.tsx (690 lines)
 *
 * Consumers should use these through the HogCharts wrappers, not directly.
 */

// ---------------------------------------------------------------------------
// 1. CSS variable color resolution (was: resolveVariableColor)
// ---------------------------------------------------------------------------

const RESOLVED_COLOR_CACHE = new Map<string, string>()

/**
 * Resolve a CSS variable or hex color to a concrete hex value.
 * Caches results to avoid repeated `getComputedStyle` calls.
 */
export function resolveColor(color: string | undefined): string | undefined {
    if (!color) {
        return color
    }
    if (RESOLVED_COLOR_CACHE.has(color)) {
        return RESOLVED_COLOR_CACHE.get(color)
    }
    if (color.startsWith('var(--')) {
        const varName = color.slice(4, -1) // strip var( and )
        const computed = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
        RESOLVED_COLOR_CACHE.set(color, computed)
        return computed
    }
    RESOLVED_COLOR_CACHE.set(color, color)
    return color
}

// ---------------------------------------------------------------------------
// 2. Tick options (identical in both)
// ---------------------------------------------------------------------------

export interface TickOptions {
    color: string
    font: {
        family: string
        size: number
        weight: string
    }
}

export function defaultTickOptions(axisLabelColor: string): TickOptions {
    return {
        color: axisLabelColor,
        font: {
            family: '"Emoji Flags Polyfill", -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"',
            size: 12,
            weight: 'normal',
        },
    }
}

// ---------------------------------------------------------------------------
// 3. Grid options (shared pattern)
// ---------------------------------------------------------------------------

export interface GridOptions {
    color: string
    tickColor: string
    tickBorderDash: number[]
}

export function defaultGridOptions(axisLineColor: string): GridOptions {
    return {
        color: axisLineColor,
        tickColor: axisLineColor,
        tickBorderDash: [4, 2],
    }
}

/**
 * Grid options that suppress lines at goal line y-values.
 * Used by the insights LineGraph to avoid double-lines where a grid line
 * and a goal line annotation overlap.
 */
export function gridOptionsWithGoalLines(
    axisLineColor: string,
    goalLineValues: Set<number | string>,
    showMultipleYAxes?: boolean
): Record<string, unknown> {
    return {
        color: (context: { tick?: { value: number } }) => {
            if (goalLineValues.has(context.tick?.value ?? NaN) || showMultipleYAxes) {
                return 'transparent'
            }
            return axisLineColor
        },
        tickColor: (context: { tick?: { value: number } }) => {
            if (goalLineValues.has(context.tick?.value ?? NaN)) {
                return 'transparent'
            }
            return axisLineColor
        },
        tickBorderDash: [4, 2],
    }
}

// ---------------------------------------------------------------------------
// 4. Crosshair plugin config (identical in both)
// ---------------------------------------------------------------------------

export function crosshairConfig(
    enabled: boolean,
    crosshairColor: string | null | undefined
): Record<string, unknown> {
    if (!enabled) {
        return { crosshair: false }
    }
    return {
        crosshair: {
            snap: { enabled: true },
            sync: { enabled: false },
            zoom: { enabled: false },
            line: { color: crosshairColor ?? undefined, width: 1 },
        },
    }
}

// ---------------------------------------------------------------------------
// 5. Goal line / annotation building (shared pattern)
// ---------------------------------------------------------------------------

export interface GoalLineInput {
    value: number
    label?: string | null
    borderColor?: string | null
    displayLabel?: boolean | null
    displayIfCrossed?: boolean | null
    position?: string | null
}

export function buildGoalLineAnnotations(
    goalLines: GoalLineInput[],
    options?: {
        scaleID?: string
        tooltipElementId?: string
    }
): Record<string, Record<string, unknown>> {
    const annotations: Record<string, Record<string, unknown>> = {}

    for (const [idx, gl] of goalLines.entries()) {
        const color = resolveColor(gl.borderColor ?? undefined)
        const annotation: Record<string, unknown> = {
            type: 'line',
            yMin: gl.value,
            yMax: gl.value,
            borderWidth: 2,
            borderDash: [6, 6],
            borderColor: color,
            label: {
                content: gl.label ?? undefined,
                display: gl.displayLabel ?? true,
                position: gl.position ?? 'end',
            },
        }

        if (options?.scaleID) {
            annotation.scaleID = options.scaleID
            annotation.value = gl.value
            // Remove yMin/yMax when using scaleID+value model
            delete annotation.yMin
            delete annotation.yMax
        }

        // Tooltip hiding on goal line hover (both implementations do this)
        if (options?.tooltipElementId) {
            const tooltipElId = options.tooltipElementId
            annotation.enter = () => {
                const el = document.getElementById(tooltipElId)
                if (el) {
                    el.classList.add('opacity-0', 'invisible')
                }
            }
            annotation.leave = () => {
                const el = document.getElementById(tooltipElId)
                if (el) {
                    el.classList.remove('opacity-0', 'invisible')
                }
            }
        }

        annotations[`line-${idx}`] = annotation
    }

    return annotations
}

// ---------------------------------------------------------------------------
// 6. Data label plugin config (shared base, both use same anchor/bg)
// ---------------------------------------------------------------------------

export function baseDataLabelsConfig(options?: {
    showValues?: boolean
    formatter?: (value: number, context: { datasetIndex: number; dataIndex: number }) => string
}): Record<string, unknown> {
    return {
        color: 'white',
        anchor: (context: { dataset: { data: unknown[] }; dataIndex: number }) => {
            const datum = context.dataset?.data[context.dataIndex]
            return typeof datum !== 'number' ? 'end' : datum > 0 ? 'end' : 'start'
        },
        backgroundColor: (context: { dataset: { borderColor?: string } }) => {
            return context.dataset?.borderColor ?? 'black'
        },
        display: options?.showValues
            ? (context: { dataset: { data: unknown[] }; dataIndex: number }) => {
                  const datum = context.dataset?.data[context.dataIndex]
                  return typeof datum === 'number' && datum !== 0 ? 'auto' : false
              }
            : () => false,
        formatter: options?.formatter ?? (() => {}),
        borderWidth: 2,
        borderRadius: 4,
        borderColor: 'white',
    }
}

// ---------------------------------------------------------------------------
// 7. Highlight bar mode (identical in both)
// ---------------------------------------------------------------------------

/**
 * Determine whether bar highlighting mode is active.
 * Both LineGraphs use the exact same formula.
 */
export function isHighlightBarMode(isBar: boolean, isStacked: boolean, isShiftPressed: boolean): boolean {
    return isBar && isStacked && isShiftPressed
}

// ---------------------------------------------------------------------------
// 8. Hover mode config (shared pattern)
// ---------------------------------------------------------------------------

export function hoverConfig(
    isBar: boolean,
    isHorizontal?: boolean
): Record<string, unknown> {
    return {
        mode: isBar ? 'point' : 'nearest',
        axis: isHorizontal ? 'y' : 'x',
        intersect: false,
    }
}

// ---------------------------------------------------------------------------
// 9. Tooltip mode config (shared pattern)
// ---------------------------------------------------------------------------

export function tooltipModeConfig(highlightMode: boolean): Record<string, unknown> {
    return {
        enabled: false,
        mode: highlightMode ? 'point' : 'index',
        intersect: highlightMode,
    }
}

// ---------------------------------------------------------------------------
// 10. Chart base options (identical structure)
// ---------------------------------------------------------------------------

export function chartBaseOptions(): Record<string, unknown> {
    return {
        responsive: true,
        maintainAspectRatio: false,
        elements: {
            line: { tension: 0 },
        },
    }
}

// ---------------------------------------------------------------------------
// 11. Dataset highlight dimming (shared pattern)
// ---------------------------------------------------------------------------

/**
 * Apply dimming to a series color when another series is highlighted.
 * Both LineGraphs dim non-hovered bars to 20% opacity.
 */
export function dimColorIfNeeded(
    color: string,
    seriesIndex: number,
    highlightIndex: number | null
): string {
    if (highlightIndex !== null && seriesIndex !== highlightIndex) {
        return hexToRGBA(color, 0.2)
    }
    return color
}

// Inline hex→rgba since both files import it from lib/utils
function hexToRGBA(hex: string, alpha: number): string {
    const clean = hex.replace('#', '')
    let r: number, g: number, b: number
    if (clean.length === 3) {
        r = parseInt(clean[0] + clean[0], 16)
        g = parseInt(clean[1] + clean[1], 16)
        b = parseInt(clean[2] + clean[2], 16)
    } else {
        r = parseInt(clean.slice(0, 2), 16)
        g = parseInt(clean.slice(2, 4), 16)
        b = parseInt(clean.slice(4, 6), 16)
    }
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// ---------------------------------------------------------------------------
// 12. Series capping with warning
// ---------------------------------------------------------------------------

/**
 * Cap the number of series and optionally show a warning.
 * DataViz caps at 200 with a toast, Insights caps at 50 silently.
 */
export function capSeries<T>(
    data: T[],
    max: number,
    onOverflow?: (total: number, max: number) => void
): T[] {
    if (data.length <= max) {
        return data
    }
    onOverflow?.(data.length, max)
    return data.slice(0, max)
}

// ---------------------------------------------------------------------------
// 13. Incompleteness segment pattern (used by Insights LineGraph)
// ---------------------------------------------------------------------------

/**
 * Build a Chart.js `segment` config that renders trailing points as dotted.
 * Used to indicate the current, still-accumulating time period.
 */
export function incompletenessSegment(
    dataLength: number,
    offset: number
): { borderDash: (ctx: { p1DataIndex: number }) => number[] | undefined } | undefined {
    if (offset <= 0) {
        return undefined
    }
    const startIndex = dataLength - offset
    return {
        borderDash: (ctx: { p1DataIndex: number }) =>
            ctx.p1DataIndex >= startIndex ? [10, 10] : undefined,
    }
}

// ---------------------------------------------------------------------------
// 14. Pinstripe pattern for incomplete area data
// ---------------------------------------------------------------------------

/**
 * Create a canvas pinstripe pattern for incomplete area fill.
 * Used by Insights LineGraph when isArea + isInProgress.
 */
export function createPinstripePattern(color: string, isDarkMode: boolean): CanvasPattern {
    const stripeWidth = 8
    const stripeAngle = -22.5
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = stripeWidth * 2
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = color
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.fillStyle = isDarkMode ? 'rgba(35, 36, 41, 0.5)' : 'rgba(255, 255, 255, 0.5)'
    ctx.fillRect(0, stripeWidth, 1, 2 * stripeWidth)
    const pattern = ctx.createPattern(canvas, 'repeat')!
    const xAx = Math.cos(stripeAngle)
    const xAy = Math.sin(stripeAngle)
    pattern.setTransform(new DOMMatrix([xAx, xAy, -xAy, xAx, 0, 0]))
    return pattern
}
