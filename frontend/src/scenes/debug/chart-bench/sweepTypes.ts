export type ChartKind = 'hog' | 'chartjs' | 'adapter-hog' | 'adapter-chartjs'

export interface SweepResult {
    chart: ChartKind
    series: number
    points: number
    runs: number
    meanReadyMs: number
    meanHoverMs: number
    readyMs: number[]
    hoverMs: number[]
}
