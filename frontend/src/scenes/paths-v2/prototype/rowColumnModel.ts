/**
 * PROTOTYPE (throwaway branch, do not merge).
 * Client-side transform of v1 PathsQuery links into the draft's row-by-column model
 * (PR #29364 semantics: per-step top-N rows, "other" bucket, drop-offs) so the layout
 * can be judged on real data without reviving the PathsV2Query backend.
 *
 * Counting caveat: v1 links are event-flow weights, not the v2 per-element unique-actor
 * contract. Node counts are approximated as max(in, out); step-1 drop-offs are invisible
 * in v1 data. Good enough to react to layout, not to numbers.
 */
import { PathsLink } from '~/queries/schema/schema-general'

export interface RowNodeMember {
    name: string
    count: number
}

export interface RowNode {
    key: string
    step: number
    name: string
    count: number
    /** users who reached this node but produced no outgoing edge (approximation, see header) */
    dropoff: number
    isOther: boolean
    members: RowNodeMember[]
}

export interface RowEdge {
    from: string
    to: string
    value: number
    /** seconds, weighted average across aggregated raw edges; null when unknown */
    avgTime: number | null
}

export interface RowColumnModel {
    columns: RowNode[][]
    edges: RowEdge[]
    stepTotals: number[]
    startTotal: number
    maxStepTotal: number
    maxEdgeValue: number
    /** steps present in the data but sliced off by maxSteps */
    hiddenSteps: number
}

const TRUNCATION_MARKER = '...'

interface RawNode {
    step: number
    name: string
    inValue: number
    outValue: number
}

function parsePathName(prefixed: string): { step: number; name: string } | null {
    const match = /^(\d+)_([\s\S]*)$/.exec(prefixed)
    if (!match) {
        return null
    }
    return { step: parseInt(match[1], 10) - 1, name: match[2] }
}

/** Strip protocol and host for URLs so column labels lead with the path. */
export function shortPathName(name: string): string {
    try {
        const url = new URL(name)
        let short = url.pathname + url.search
        if (url.hash?.includes('/')) {
            short += url.hash
        }
        return short || name
    } catch {
        return name
    }
}

export function middleEllipsis(name: string, max: number): string {
    if (name.length <= max) {
        return name
    }
    const head = Math.ceil((max - 1) * 0.6)
    const tail = max - 1 - head
    return `${name.slice(0, head)}…${name.slice(name.length - tail)}`
}

export function buildRowColumnModel(links: PathsLink[], maxSteps: number, maxRows: number): RowColumnModel {
    const nodeMap = new Map<string, RawNode>()
    const rawEdges: { fromStep: number; fromName: string; toName: string; value: number; avgTime: number }[] = []

    for (const link of links) {
        const source = parsePathName(link.source)
        const target = parsePathName(link.target)
        if (!source || !target || target.step !== source.step + 1) {
            continue
        }
        const sourceKey = `${source.step}:${source.name}`
        const targetKey = `${target.step}:${target.name}`
        const sourceNode = nodeMap.get(sourceKey) ?? { step: source.step, name: source.name, inValue: 0, outValue: 0 }
        sourceNode.outValue += link.value
        nodeMap.set(sourceKey, sourceNode)
        const targetNode = nodeMap.get(targetKey) ?? { step: target.step, name: target.name, inValue: 0, outValue: 0 }
        targetNode.inValue += link.value
        nodeMap.set(targetKey, targetNode)
        rawEdges.push({
            fromStep: source.step,
            fromName: source.name,
            toName: target.name,
            value: link.value,
            avgTime: link.average_conversion_time,
        })
    }

    if (nodeMap.size === 0) {
        return {
            columns: [],
            edges: [],
            stepTotals: [],
            startTotal: 0,
            maxStepTotal: 0,
            maxEdgeValue: 0,
            hiddenSteps: 0,
        }
    }

    const availableSteps = Math.max(...Array.from(nodeMap.values()).map((n) => n.step)) + 1
    const visibleSteps = Math.min(maxSteps, availableSteps)
    const hiddenSteps = availableSteps - visibleSteps

    // bucket each visible column into top-N rows + "other"
    const columns: RowNode[][] = []
    const keyByRawNode = new Map<string, string>() // `${step}:${name}` -> RowNode.key
    for (let step = 0; step < visibleSteps; step++) {
        const columnNodes = Array.from(nodeMap.values())
            .filter((n) => n.step === step)
            .map((n) => ({ ...n, count: Math.max(n.inValue, n.outValue) }))
            .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))

        const rows = columnNodes.filter((n) => n.name !== TRUNCATION_MARKER).slice(0, maxRows)
        const bucketed = columnNodes.filter((n) => !rows.includes(n))

        const column: RowNode[] = rows.map((n) => {
            const key = `${step}:${n.name}`
            keyByRawNode.set(key, key)
            return {
                key,
                step,
                name: n.name,
                count: n.count,
                dropoff: Math.max(0, n.count - n.outValue),
                isOther: false,
                members: [],
            }
        })

        if (bucketed.length > 0) {
            const otherKey = `${step}:$$other$$`
            for (const n of bucketed) {
                keyByRawNode.set(`${step}:${n.name}`, otherKey)
            }
            column.push({
                key: otherKey,
                step,
                name: 'Other',
                count: bucketed.reduce((sum, n) => sum + n.count, 0),
                dropoff: bucketed.reduce((sum, n) => sum + Math.max(0, n.count - n.outValue), 0),
                isOther: true,
                members: bucketed.map((n) => ({
                    name: n.name === TRUNCATION_MARKER ? 'Deeper steps' : n.name,
                    count: n.count,
                })),
            })
        }
        columns.push(column)
    }

    // aggregate raw edges onto bucketed nodes
    const edgeMap = new Map<string, { value: number; timeWeighted: number; timeValue: number }>()
    for (const raw of rawEdges) {
        if (raw.fromStep + 1 >= visibleSteps) {
            continue
        }
        const from = keyByRawNode.get(`${raw.fromStep}:${raw.fromName}`)
        const to = keyByRawNode.get(`${raw.fromStep + 1}:${raw.toName}`)
        if (!from || !to) {
            continue
        }
        const key = `${from}→${to}`
        const agg = edgeMap.get(key) ?? { value: 0, timeWeighted: 0, timeValue: 0 }
        agg.value += raw.value
        if (raw.avgTime != null) {
            agg.timeWeighted += raw.avgTime * raw.value
            agg.timeValue += raw.value
        }
        edgeMap.set(key, agg)
    }
    const edges: RowEdge[] = Array.from(edgeMap.entries()).map(([key, agg]) => {
        const [from, to] = key.split('→')
        return { from, to, value: agg.value, avgTime: agg.timeValue > 0 ? agg.timeWeighted / agg.timeValue : null }
    })

    const stepTotals = columns.map((column) => column.reduce((sum, node) => sum + node.count, 0))
    return {
        columns,
        edges,
        stepTotals,
        startTotal: stepTotals[0] ?? 0,
        maxStepTotal: Math.max(...stepTotals, 0),
        maxEdgeValue: Math.max(...edges.map((e) => e.value), 0),
        hiddenSteps,
    }
}

/** Filled ribbon between two vertical port segments, for SVG overlays. */
export function ribbonPath(x0: number, y0: number, t0: number, x1: number, y1: number, t1: number): string {
    const xm = (x0 + x1) / 2
    return [
        `M ${x0},${y0}`,
        `C ${xm},${y0} ${xm},${y1} ${x1},${y1}`,
        `L ${x1},${y1 + t1}`,
        `C ${xm},${y1 + t1} ${xm},${y0 + t0} ${x0},${y0 + t0}`,
        'Z',
    ].join(' ')
}

export function formatPercentage(part: number, whole: number): string {
    if (whole <= 0) {
        return '0%'
    }
    const pct = (part / whole) * 100
    return `${pct < 1 && pct > 0 ? pct.toFixed(1) : Math.round(pct)}%`
}
