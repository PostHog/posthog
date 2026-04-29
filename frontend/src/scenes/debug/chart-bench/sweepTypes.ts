export type ChartKind = 'hog' | 'chartjs' | 'adapter-hog' | 'adapter-chartjs'

export interface SweepResult {
    chart: ChartKind
    series: number
    points: number
    runs: number
    meanReadyMs: number
    meanHoverMs: number
    /** Mean time per mousemove spent synchronously in event dispatch (React handler + setState + sync effects). */
    meanHoverSyncMs: number
    /** Mean time per mousemove spent awaiting the next animation frame after dispatch returns. */
    meanHoverFrameMs: number
    readyMs: number[]
    hoverMs: number[]
}
