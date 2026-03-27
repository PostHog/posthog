// Re-export shared chart types from the existing lib/charts
export type { AxisFormat, ChartTheme } from 'lib/charts/types'

export interface Series {
    /** Unique identifier */
    key: string
    /** Display name */
    label: string
    /** Values (same length as labels) */
    data: number[]
    /** Hex color */
    color: string
    /** For multi-axis ('y', 'y1', 'y2', ...) */
    yAxisId?: string
    /** Area fill under the line */
    fillArea?: boolean
    /** 0-1, defaults to 0.5 */
    fillOpacity?: number
    /** e.g. [10, 10] for dashed */
    dashPattern?: number[]
    /** Don't render this series */
    hidden?: boolean
    /** Data point dot size (0 = no dots) */
    pointRadius?: number
}

export interface GoalLine {
    /** Y-axis value */
    value: number
    /** Text label */
    label?: string
    /** Line color */
    borderColor?: string
    /** Label position */
    position?: 'start' | 'end'
}

export interface PointClickData {
    seriesIndex: number
    dataIndex: number
    series: Series
    value: number
    label: string
    crossSeriesData: { series: Series; value: number }[]
}

export interface TooltipContext {
    dataIndex: number
    label: string
    seriesData: { series: Series; value: number; color: string }[]
    position: { x: number; y: number }
    canvasBounds: DOMRect
}

export interface ChartDimensions {
    width: number
    height: number
    plotLeft: number
    plotTop: number
    plotWidth: number
    plotHeight: number
}

export interface ChartMargins {
    top: number
    right: number
    bottom: number
    left: number
}
