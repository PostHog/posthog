import type { Series } from '@posthog/quill-charts'

import type { DataFrame } from './vizTypes'

/**
 * Turns frames that each hold a `time` field and a number field into one set of x-axis labels and one series per
 * frame, the shape the time-series charts take. Labels come from the first frame, and every frame is read against them.
 */
export function timeSeriesFromFrames(frames: DataFrame[]): { labels: string[]; series: Series[] } {
    const timeOf = (frame: DataFrame): unknown[] => frame.fields.find((field) => field.type === 'time')?.values ?? []
    const labels = timeOf(frames[0] ?? { fields: [] }).map(String)
    const series = frames.map((frame, index) => {
        const values = frame.fields.find((field) => field.type === 'number')?.values ?? []
        return {
            key: frame.name ?? `series-${index}`,
            label: frame.name ?? `Series ${index + 1}`,
            data: labels.map((_, position) => {
                const value = values[position]
                return typeof value === 'number' ? value : NaN
            }),
        }
    })
    return { labels, series }
}
