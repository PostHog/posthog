const RESOLVED_COLOR_CACHE = new Map<string, string>()

export function resolveColor(color: string | undefined): string | undefined {
    if (!color) {
        return color
    }
    if (RESOLVED_COLOR_CACHE.has(color)) {
        return RESOLVED_COLOR_CACHE.get(color)
    }
    if (color.startsWith('var(--')) {
        const varName = color.slice(4, -1)
        const computed = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
        RESOLVED_COLOR_CACHE.set(color, computed)
        return computed
    }
    RESOLVED_COLOR_CACHE.set(color, color)
    return color
}

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

/** Suppresses grid lines at goal line y-values to avoid visual overlap. */
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
            // chartjs-plugin-annotation uses scaleID+value instead of yMin/yMax
            delete annotation.yMin
            delete annotation.yMax
        }

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

export function isHighlightBarMode(isBar: boolean, isStacked: boolean, isShiftPressed: boolean): boolean {
    return isBar && isStacked && isShiftPressed
}

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

export function tooltipModeConfig(highlightMode: boolean): Record<string, unknown> {
    return {
        enabled: false,
        mode: highlightMode ? 'point' : 'index',
        intersect: highlightMode,
    }
}

export function chartBaseOptions(): Record<string, unknown> {
    return {
        responsive: true,
        maintainAspectRatio: false,
        elements: {
            line: { tension: 0 },
        },
    }
}

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

/** Returns a Chart.js segment config that renders trailing points as dotted (in-progress period). */
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
