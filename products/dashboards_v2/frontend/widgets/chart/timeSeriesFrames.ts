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

// Series names can change on every refresh, so only this many colours are kept for keys that are no longer drawn.
export const MAX_REMEMBERED_COLORS = 500

/**
 * Picks a palette colour from each series' key rather than its position, so a series keeps its colour when another
 * target fails or returns more series. `assigned` holds the colours given out before and is added to. A key keeps its
 * remembered colour unless an earlier key drawn alongside it holds that colour. Keys without one take their hashed
 * slot, or the next free one, in key order.
 */
export function stableSeriesColors(
    keys: string[],
    palette: string[],
    assigned: Map<string, string> = new Map()
): Map<string, string> {
    const colors = new Map<string, string>()
    if (palette.length === 0) {
        return colors
    }
    const sorted = [...new Set(keys)].sort()
    const taken = new Set<number>()
    for (const key of sorted) {
        const slot = palette.indexOf(assigned.get(key) ?? '')
        if (slot >= 0 && !taken.has(slot)) {
            taken.add(slot)
            colors.set(key, palette[slot])
        }
    }
    for (const key of sorted) {
        if (colors.has(key)) {
            continue
        }
        let slot = hash(key) % palette.length
        for (let tries = 0; taken.has(slot) && tries < palette.length; tries++) {
            slot = (slot + 1) % palette.length
        }
        taken.add(slot)
        assigned.set(key, palette[slot])
        colors.set(key, palette[slot])
    }
    for (const key of assigned.keys()) {
        if (assigned.size <= MAX_REMEMBERED_COLORS) {
            break
        }
        if (!colors.has(key)) {
            assigned.delete(key)
        }
    }
    return colors
}

function timeOf(label: string): number {
    return label.trim() !== '' && Number.isFinite(Number(label)) ? Number(label) : Date.parse(label)
}

// Frames can hold different timestamps, so the merged labels are put back in time order. A label that is not a time
// keeps its place.
function inTimeOrder(a: string, b: string): number {
    const difference = timeOf(a) - timeOf(b)
    return Number.isNaN(difference) ? 0 : difference
}

/** Joins times by the instant they name, so a date-only `2026-11-01` meets a full `2026-11-01T00:00:00.000Z`. */
function timeKey(value: unknown): string {
    const text = String(value)
    const ms = timeOf(text)
    return Number.isFinite(ms) ? String(ms) : text
}

/**
 * Turns frames that each hold a `time` field and a number field into one set of x-axis labels and one series per
 * frame, the shape the time-series charts take. Frames are joined on their timestamps, so a frame with no value at a
 * timestamp gets a gap there. Frames from several targets are drawn together: each keeps its own series, a second
 * unit gets its own axis, and, given a `palette`, each series a colour that does not move between refreshes. Pass the
 * same `assignedColors` map on every refresh to keep those colours when a colliding series comes and goes.
 */
export function timeSeriesFromFrames(
    frames: DataFrame[],
    palette?: string[],
    assignedColors?: Map<string, string>
): TimeSeriesData {
    const keyByTime = new Map<string, string>()
    const keyOf = (time: unknown): string => {
        const text = String(time)
        let key = keyByTime.get(text)
        if (key === undefined) {
            key = timeKey(text)
            keyByTime.set(text, key)
        }
        return key
    }
    const labelByKey = new Map<string, string>()
    for (const time of frames.flatMap((frame) => fieldValues(frame, 'time').map(String))) {
        const key = keyOf(time)
        const existing = labelByKey.get(key)
        if (existing === undefined || time.length > existing.length) {
            labelByKey.set(key, time)
        }
    }
    const labels = [...labelByKey.values()].sort(inTimeOrder)
    const labelKeys = labels.map(keyOf)
    const multiTarget = frames.some((frame) => frame.refId !== undefined)
    // A frame without a unit, such as an event count, gets its own axis next to one that has a unit, such as latency.
    const units = [...new Set(frames.map(unitOf))]
    const axes =
        units.length > 1 || units[0]
            ? units.map((unit, index) => ({ id: index === 0 ? 'left' : `unit-${index}`, unit }))
            : []
    // A legend such as `{{job}}` can give several frames of one target the same name, and the chart needs unique keys.
    const keyCounts = new Map<string, number>()
    const series = frames.map((frame, index): Series => {
        const values = fieldValues(frame, 'number')
        const axis = axes.find((candidate) => candidate.unit === unitOf(frame))
        const byTime = new Map(fieldValues(frame, 'time').map((time, position) => [keyOf(time), values[position]]))
        const name = frame.name ?? (multiTarget ? `${frame.refId}` : `Series ${index + 1}`)
        const baseKey = multiTarget ? `${frame.refId}:${frame.name ?? index}` : (frame.name ?? `series-${index}`)
        const repeats = keyCounts.get(baseKey) ?? 0
        keyCounts.set(baseKey, repeats + 1)
        return {
            key: repeats === 0 ? baseKey : `${baseKey}#${repeats + 1}`,
            label: name,
            data: labelKeys.map((labelKey) => {
                const value = byTime.get(labelKey)
                return typeof value === 'number' ? value : NaN
            }),
            ...(axis && axis.id !== 'left' ? { yAxisId: axis.id } : {}),
        }
    })
    if (multiTarget && palette) {
        const colors = stableSeriesColors(
            series.map((one) => one.key),
            palette,
            assignedColors
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
