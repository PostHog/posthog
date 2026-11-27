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

// Past this, a chart lays out and draws more slices, rows or steps than any tile can show.
export const MAX_CATEGORIES = 50

/** The largest `MAX_CATEGORIES` of `series`, kept in their order, since a funnel's order is its steps. */
function largest(series: Series[]): Series[] {
    if (series.length <= MAX_CATEGORIES) {
        return series
    }
    const kept = new Set([...series].sort((a, b) => b.data[0] - a.data[0]).slice(0, MAX_CATEGORIES))
    return series.filter((one) => kept.has(one))
}

/**
 * One series per category, the shape the part-of-a-whole charts take. Frames with a string field give one category
 * per row. Frames without one, such as time series or totals, give one category per frame, valued by the sum of its
 * numbers. Only the largest `MAX_CATEGORIES` are kept.
 */
export function categoriesFromFrames(frames: DataFrame[]): Series[] {
    if (fieldsOf(frames[0], 'string').length > 0) {
        return largest(
            frames.flatMap((frame, index) => {
                const [labels] = fieldsOf(frame, 'string')
                const [values] = fieldsOf(frame, 'number')
                return labels && values
                    ? labels.values.map((label, row) => ({
                          key: `${index}:${String(label)}#${row}`,
                          label: String(label),
                          data: [Number(values.values[row]) || 0],
                      }))
                    : []
            })
        )
    }
    // Summed from the frame, not the time series, because a total has no time to line its numbers up against.
    return largest(
        timeSeriesFromFrames(frames).series.map((series, index) => ({
            ...series,
            data: [sum(fieldValues(frames[index], 'number'))],
        }))
    )
}

export function latestValue(frames: DataFrame[]): number | null {
    return finite(frames[0] ? fieldValues(frames[0], 'number') : []).at(-1) ?? null
}

export function heatmapFromFrames(frames: DataFrame[]): { xLabels: string[]; yLabels: string[]; cells: number[][] } {
    const { labels, series } = timeSeriesFromFrames(frames.slice(0, MAX_CATEGORIES))
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
        // A series without a value at an end keeps the gap there, so no value is shown at a date it was not measured.
        series: series.map((one) => ({ ...one, data: [one.data[0] ?? NaN, one.data.at(-1) ?? NaN] })),
    }
}

const ROOT = 'All'
// Kept apart from category names, so a category called `All` does not flow into itself.
const ROOT_ID = '\u0000root'

/**
 * Flows from a frame with a source and a target string field and a number field, one link per row. Without them, each
 * frame flows from one root, valued by the sum of its numbers.
 */
export function flowsFromFrames(frames: DataFrame[]): { nodes: SankeyNodeInput[]; links: SankeyLinkInput[] } {
    const [sources, targets] = fieldsOf(frames[0], 'string')
    const [values] = fieldsOf(frames[0], 'number')
    if (sources && targets && values) {
        const links = sources.values.map((source, row) => ({
            source: String(source),
            target: String(targets.values[row]),
            value: Number(values.values[row]) || 0,
        }))
        const ids = [...new Set(links.flatMap((link) => [link.source, link.target]))]
        return { nodes: ids.map((id) => ({ id })), links: links.filter((link) => link.value > 0) }
    }
    const categories = categoriesFromFrames(frames).filter((one) => one.data[0] > 0)
    return {
        nodes: [{ id: ROOT_ID, label: ROOT }, ...categories.map((one) => ({ id: one.key, label: one.label }))],
        links: categories.map((one) => ({ source: ROOT_ID, target: one.key, value: one.data[0] })),
    }
}

// A stack is one query cell, so without these one long string would build a node per segment.
const MAX_STACK_DEPTH = 256
const MAX_FLAME_NODES = 10_000

/**
 * A tree from folded stacks: a frame with a string field such as `main;render;paint` and a number field, one stack per
 * row. Without a string field, each frame is one child of a single root, valued by the sum of its numbers. Past
 * `MAX_STACK_DEPTH` frames or `MAX_FLAME_NODES` nodes, a stack's value stays on the deepest node already in the tree.
 */
export function flameFromFrames(frames: DataFrame[]): FlameNode {
    const [stacks] = fieldsOf(frames[0], 'string')
    const [values] = fieldsOf(frames[0], 'number')
    const root: FlameNode = { id: ROOT, name: ROOT, value: 0, children: [] }
    const rows: [string[], number][] =
        stacks && values
            ? stacks.values.map((stack, row) => [
                  String(stack).split(';', MAX_STACK_DEPTH),
                  Number(values.values[row]) || 0,
              ])
            : categoriesFromFrames(frames).map((one) => [[one.label], one.data[0]])
    const childrenOf = new Map<FlameNode, Map<string, FlameNode>>()
    let nodes = 1
    for (const [path, value] of rows) {
        root.value += value
        let node = root
        for (const name of path) {
            let byName = childrenOf.get(node)
            if (!byName) {
                byName = new Map()
                childrenOf.set(node, byName)
            }
            let child = byName.get(name)
            if (!child) {
                if (nodes >= MAX_FLAME_NODES) {
                    break
                }
                // A counter, not the ancestor path, so an id stays short however deep its node is.
                child = { id: `node-${nodes++}`, name, value: 0, children: [] }
                byName.set(name, child)
                node.children?.push(child)
            }
            child.value += value
            node = child
        }
    }
    return root
}
