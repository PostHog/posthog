import type { Series, YAxisConfig } from '@posthog/quill-charts'

import type { DataFrame } from './vizTypes'

export interface TimeSeriesData {
    labels: string[]
    series: Series[]
    axes: { id: string; unit: string }[]
    /** True when the series come from more than one target, which may sample on different time steps. */
    multiTarget: boolean
}

function fieldValues(frame: DataFrame, type: DataFrame['fields'][number]['type']): unknown[] {
    return frame.fields.find((field) => field.type === type)?.values ?? []
}

function unitOf(frame: DataFrame): string {
    return frame.fields.find((field) => field.type === 'number')?.unit ?? ''
}

function hash(text: string): number {
    return [...text].reduce((value, char) => (value * 31 + char.charCodeAt(0)) >>> 0, 7)
}

/**
 * Picks a palette colour from each series' key rather than its position, so a series keeps its colour when another
 * target fails or returns more series. Two keys that hash to the same colour take the next free one, in key order.
 */
export function stableSeriesColors(keys: string[], palette: string[]): Map<string, string> {
    const colors = new Map<string, string>()
    if (palette.length === 0) {
        return colors
    }
    const taken = new Set<number>()
    for (const key of [...keys].sort()) {
        let slot = hash(key) % palette.length
        for (let tries = 0; taken.has(slot) && tries < palette.length; tries++) {
            slot = (slot + 1) % palette.length
        }
        taken.add(slot)
        colors.set(key, palette[slot])
    }
    return colors
}

/**
 * Turns frames that each hold a `time` field and a number field into one set of x-axis labels and one series per
 * frame, the shape the time-series charts take. Frames are joined on their timestamps, so a frame with no value at a
 * timestamp gets a gap there. Frames from several targets are drawn together: each keeps its own series, a second
 * unit gets its own axis, and, given a `palette`, each series a colour that does not move between refreshes.
 */
export function timeSeriesFromFrames(frames: DataFrame[], palette?: string[]): TimeSeriesData {
    const labels = [...new Set(frames.flatMap((frame) => fieldValues(frame, 'time').map(String)))].sort()
    const multiTarget = frames.some((frame) => frame.refId !== undefined)
    // A frame without a unit, such as an event count, gets its own axis next to one that has a unit, such as latency.
    const units = [...new Set(frames.map(unitOf))]
    const axes =
        units.length > 1 ? units.map((unit, index) => ({ id: index === 0 ? 'left' : `unit-${index}`, unit })) : []
    const series = frames.map((frame, index): Series => {
        const values = fieldValues(frame, 'number')
        const axis = axes.find((candidate) => candidate.unit === unitOf(frame))
        const byTime = new Map(fieldValues(frame, 'time').map((time, position) => [String(time), values[position]]))
        const name = frame.name ?? (multiTarget ? `${frame.refId}` : `Series ${index + 1}`)
        return {
            key: multiTarget ? `${frame.refId}:${frame.name ?? index}` : (frame.name ?? `series-${index}`),
            label: name,
            data: labels.map((label) => {
                const value = byTime.get(label)
                return typeof value === 'number' ? value : NaN
            }),
            ...(axis && axis.id !== 'left' ? { yAxisId: axis.id } : {}),
        }
    })
    if (multiTarget && palette) {
        const colors = stableSeriesColors(
            series.map((one) => one.key),
            palette
        )
        series.forEach((one) => (one.color = colors.get(one.key)))
    }
    return { labels, series, axes, multiTarget }
}

const UNIT_FORMATS: Record<string, YAxisConfig['format']> = { s: 'duration', ms: 'duration_ms', ns: 'duration_ns' }

export function yAxisFor(axes: TimeSeriesData['axes']): YAxisConfig | YAxisConfig[] {
    if (axes.length === 0) {
        return { showGrid: true }
    }
    return axes.map(({ id, unit }, index) => ({
        id,
        position: index === 0 ? 'left' : 'right',
        // A duration axis already prints its unit on every tick.
        ...(UNIT_FORMATS[unit] ? { format: UNIT_FORMATS[unit] } : unit ? { label: unit } : {}),
        showGrid: index === 0,
    }))
}
