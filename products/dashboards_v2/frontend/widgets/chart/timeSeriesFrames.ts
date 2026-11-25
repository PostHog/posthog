import type { Series } from '@posthog/quill-charts'

import type { DataFrame } from './vizTypes'

function fieldValues(frame: DataFrame, type: DataFrame['fields'][number]['type']): unknown[] {
    return frame.fields.find((field) => field.type === type)?.values ?? []
}

/**
 * Turns frames that each hold a `time` field and a number field into one set of x-axis labels and one series per
 * frame, the shape the time-series charts take. Frames are joined on their timestamps, so a frame with no value at a
 * timestamp gets a gap there.
 */
export function timeSeriesFromFrames(frames: DataFrame[]): { labels: string[]; series: Series[] } {
    const labels = [...new Set(frames.flatMap((frame) => fieldValues(frame, 'time').map(String)))]
    const series = frames.map((frame, index) => {
        const values = fieldValues(frame, 'number')
        const byTime = new Map(fieldValues(frame, 'time').map((time, position) => [String(time), values[position]]))
        return {
            key: frame.name ?? `series-${index}`,
            label: frame.name ?? `Series ${index + 1}`,
            data: labels.map((label) => {
                const value = byTime.get(label)
                return typeof value === 'number' ? value : NaN
            }),
        }
    })
    return { labels, series }
}
