export type ChartKind = 'hog' | 'chartjs' | 'hog-bar' | 'adapter-hog' | 'adapter-chartjs' | 'adapter-bar'

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
