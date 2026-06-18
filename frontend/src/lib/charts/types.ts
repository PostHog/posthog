export type AxisFormat = 'number' | 'compact' | 'percent' | 'duration' | 'duration_ms' | 'date' | 'datetime' | 'none'

export interface ChartTheme {
    colors: string[]
    /** Required by radial charts (PieChart) for the hover pop-out mask — without it the pop-out is skipped. */
    backgroundColor?: string
    axisColor?: string
    gridColor?: string
    crosshairColor?: string
    tooltipBackground?: string
    tooltipColor?: string
    tooltipZIndex?: number | string
    /** Skip canvas painting while still mounting the canvas. For deterministic visual-snapshot tests. */
    skipDraw?: boolean
}
