export type AxisFormat = 'number' | 'compact' | 'percent' | 'duration' | 'duration_ms' | 'date' | 'datetime' | 'none'

export interface ChartTheme {
    colors: string[]
    backgroundColor?: string
    axisColor?: string
    gridColor?: string
    crosshairColor?: string
    tooltipBackground?: string
    tooltipColor?: string
}
