import type {
    BoxPlotDatum,
    BoxPlotSeries,
    FlameNode,
    ScatterSeries,
    SankeyLinkInput,
    SankeyNodeInput,
    Series,
} from '@posthog/quill-charts'

import type { DataFrame } from '../../../query/queryTypes'
import { fieldValues, timeSeriesFromFrames } from './timeSeriesFrames'

type FieldType = DataFrame['fields'][number]['type']

function fieldsOf(frame: DataFrame | undefined, type: FieldType): DataFrame['fields'] {
    return frame?.fields.filter((field) => field.type === type) ?? []
}

function finite(values: unknown[]): number[] {
    return values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
}

function sum(values: unknown[]): number {
    return finite(values).reduce((total, value) => total + value, 0)
}

/**
 * One series per category, the shape the part-of-a-whole charts take. A frame with a string field gives one category
 * per row. Frames without one, such as time series, give one category per frame, valued by the sum of its numbers.
 */
export function categoriesFromFrames(frames: DataFrame[]): Series[] {
    const [labels] = fieldsOf(frames[0], 'string')
    const [values] = fieldsOf(frames[0], 'number')
    if (labels && values) {
        return labels.values.map((label, row) => ({
            key: `${String(label)}#${row}`,
            label: String(label),
            data: [Number(values.values[row]) || 0],
        }))
    }
    return timeSeriesFromFrames(frames).series.map((series) => ({ ...series, data: [sum(series.data)] }))
}

export function latestValue(frames: DataFrame[]): number | null {
    return finite(frames[0] ? fieldValues(frames[0], 'number') : []).at(-1) ?? null
}

export function heatmapFromFrames(frames: DataFrame[]): { xLabels: string[]; yLabels: string[]; cells: number[][] } {
    const { labels, series } = timeSeriesFromFrames(frames)
    return {
        xLabels: labels,
        yLabels: series.map((one) => one.label),
        cells: series.map((one) => one.data.map((value) => (Number.isFinite(value) ? value : 0))),
    }
}

/**
 * One series per frame. When every frame has two number fields, each plots the first against the second. Otherwise
 * each plots its number against time, in milliseconds.
 */
export function scatterFromFrames(frames: DataFrame[]): { series: ScatterSeries[]; overTime: boolean } {
    const overTime = frames.some((frame) => fieldsOf(frame, 'number').length < 2)
    const series = frames.map((frame, index) => {
        const [first, second] = fieldsOf(frame, 'number')
        const xs = overTime ? fieldValues(frame, 'time').map((time) => Date.parse(String(time))) : first.values
        const ys = (overTime ? first : second)?.values ?? []
        return {
            key: frame.name ?? `series-${index}`,
            label: frame.name ?? `Series ${index + 1}`,
            points: ys.flatMap((y, row) => {
                const x = Number(xs[row])
                return typeof y === 'number' && Number.isFinite(x) ? [{ x, y }] : []
            }),
        }
    })
    return { series, overTime }
}

function quantile(sorted: number[], q: number): number {
    const position = (sorted.length - 1) * q
    const below = Math.floor(position)
    const above = Math.ceil(position)
    return sorted[below] + (sorted[above] - sorted[below]) * (position - below)
}

function summary(values: unknown[]): BoxPlotDatum | null {
    const sorted = finite(values).sort((a, b) => a - b)
    if (sorted.length === 0) {
        return null
    }
    return {
        min: sorted[0],
        p25: quantile(sorted, 0.25),
        median: quantile(sorted, 0.5),
        mean: sum(sorted) / sorted.length,
        p75: quantile(sorted, 0.75),
        max: sorted[sorted.length - 1],
    }
}

export function boxPlotFromFrames(frames: DataFrame[]): { labels: string[]; series: BoxPlotSeries[] } {
    return {
        labels: frames.map((frame, index) => frame.name ?? `Series ${index + 1}`),
        series: [
            {
                key: 'distribution',
                label: 'Distribution',
                data: frames.map((frame) => summary(fieldValues(frame, 'number'))),
            },
        ],
    }
}

export function slopeFromFrames(frames: DataFrame[]): { labels: string[]; series: Series[] } {
    const { labels, series } = timeSeriesFromFrames(frames)
    if (labels.length < 2) {
        return { labels: [], series: [] }
    }
    return {
        labels: [labels[0], labels[labels.length - 1]],
        series: series.map((one) => {
            const values = one.data.filter(Number.isFinite)
            return { ...one, data: [values[0] ?? NaN, values.at(-1) ?? NaN] }
        }),
    }
}

const ROOT = 'All'

/**
 * Flows from a frame with a source and a target string field and a number field, one link per row. Without them, each
 * frame flows from one root, valued by the sum of its numbers.
 */
export function flowsFromFrames(frames: DataFrame[]): { nodes: SankeyNodeInput[]; links: SankeyLinkInput[] } {
    const [sources, targets] = fieldsOf(frames[0], 'string')
    const [values] = fieldsOf(frames[0], 'number')
    const links: SankeyLinkInput[] =
        sources && targets && values
            ? sources.values.map((source, row) => ({
                  source: String(source),
                  target: String(targets.values[row]),
                  value: Number(values.values[row]) || 0,
              }))
            : categoriesFromFrames(frames).map((one) => ({ source: ROOT, target: one.label, value: one.data[0] }))
    const ids = [...new Set(links.flatMap((link) => [link.source, link.target]))]
    return { nodes: ids.map((id) => ({ id })), links: links.filter((link) => link.value > 0) }
}

/**
 * A tree from folded stacks: a frame with a string field such as `main;render;paint` and a number field, one stack per
 * row. Without a string field, each frame is one child of a single root, valued by the sum of its numbers.
 */
export function flameFromFrames(frames: DataFrame[]): FlameNode {
    const [stacks] = fieldsOf(frames[0], 'string')
    const [values] = fieldsOf(frames[0], 'number')
    const root: FlameNode = { id: ROOT, name: ROOT, value: 0, children: [] }
    const rows: [string[], number][] =
        stacks && values
            ? stacks.values.map((stack, row) => [String(stack).split(';'), Number(values.values[row]) || 0])
            : categoriesFromFrames(frames).map((one) => [[one.label], one.data[0]])
    for (const [path, value] of rows) {
        root.value += value
        let node = root
        for (const name of path) {
            const id = `${node.id};${name}`
            let child = node.children?.find((candidate) => candidate.id === id)
            if (!child) {
                child = { id, name, value: 0, children: [] }
                node.children?.push(child)
            }
            child.value += value
            node = child
        }
    }
    return root
}
