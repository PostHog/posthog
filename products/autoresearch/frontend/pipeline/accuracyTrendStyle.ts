import { AccuracyTrendSeries } from '../onlinePerformance'

export interface TrendLineStyle {
    /** Tailwind classes that set the stroke color. */
    stroke: string
    dash: string | undefined
}

// Static class names, so Tailwind keeps them.
const CHALLENGER_STROKES = [
    'stroke-[var(--data-color-2)]',
    'stroke-[var(--data-color-3)]',
    'stroke-[var(--data-color-4)]',
    'stroke-[var(--data-color-5)]',
]
const CHALLENGER_DASHES = ['6 4', '2 3']

/** One style per series, in series order. Lines differ by dash as well as color, so they stay apart without color. */
export function trendLineStyles(series: AccuracyTrendSeries[]): TrendLineStyle[] {
    let challengerIndex = 0
    return series.map((s) => {
        switch (s.role) {
            case 'champion':
                return { stroke: 'stroke-[var(--data-color-1)]', dash: undefined }
            case 'actual':
                return { stroke: 'stroke-current text-secondary', dash: '6 4' }
            case 'challenger': {
                const index = challengerIndex++
                return {
                    stroke: CHALLENGER_STROKES[index % CHALLENGER_STROKES.length],
                    dash: CHALLENGER_DASHES[index % CHALLENGER_DASHES.length],
                }
            }
        }
    })
}
