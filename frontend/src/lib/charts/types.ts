import type { ChartSettingsDisplay, ChartSettingsFormatting } from '~/queries/schema/schema-general'

export type AxisFormat = 'number' | 'compact' | 'percent' | 'duration' | 'duration_ms' | 'date' | 'datetime' | 'none'

/** Per-series display settings from a saved insight's chart config — the `AxisSeriesSettings`
 *  shape data viz stores per y-axis column, reduced to what chart rendering reads. */
export interface ChartSeriesSettings {
    formatting?: ChartSettingsFormatting
    display?: ChartSettingsDisplay
}

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
