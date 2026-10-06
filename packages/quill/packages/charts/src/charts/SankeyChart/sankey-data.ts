import { sankeyCenter, sankeyJustify, sankeyLayout, sankeyLeft, sankeyRight } from './sankey-layout'

/** A node of the flow graph. `id` must be unique; a node that occurs at several stages of a
 *  flow (the same tool called twice in a row) needs one node per stage, so prefix the id with the
 *  stage. Nodes with the same `label` share a palette color, so the repeated tool still reads
 *  as one thing. */
export interface SankeyNodeInput<Meta = unknown> {
    id: string
    /** Display label. Defaults to `id`. */
    label?: string
    /** CSS color (hex, rgb, or `var(--…)`, resolved by the chart). Omit to pick a palette color
     *  by label. */
    color?: string
    /** Consumer data handed back through tooltips and click handlers. */
    meta?: Meta
    /** Pin the node to this zero-based column. Use it when the data carries its own stage (the
     *  step in a paths result), so a flow that ends early or starts late still sits under the right
     *  `columnLabels` header. Nodes without a pin follow `nodeAlign`. Pins must be monotonic with
     *  the graph's edges — a link whose target column is at or before its source's draws backwards.
     *  A pin that is not a whole number from 0 to `MAX_SANKEY_COLUMN` throws. */
    column?: number
}

/** A directed flow from `source` to `target` (both node ids). The graph must be acyclic. */
export interface SankeyLinkInput<Meta = unknown> {
    source: string
    target: string
    value: number
    /** CSS color for the ribbon. Defaults to the source node's color. */
    color?: string
    /** Consumer data handed back through tooltips and click handlers. */
    meta?: Meta
}

/** How nodes spread across columns when a flow ends early. Mirrors d3-sankey's alignments. */
export type SankeyNodeAlign = 'left' | 'right' | 'center' | 'justify'

export interface SankeyNodeDatum<Meta = unknown> {
    id: string
    label: string
    color: string
    meta?: Meta
    /** Position in the `nodes` prop and in `layout.nodes`. */
    index: number
    column: number
    /** Sum of the larger side's link values (in or out). */
    value: number
    x0: number
    x1: number
    y0: number
    y1: number
}

/** A laid-out link: the input plus the ribbon geometry. `y0` is the centerline y at the source
 *  edge, `y1` at the target edge; `width` is the ribbon thickness. */
export interface SankeyLinkDatum<NodeMeta = unknown, LinkMeta = NodeMeta> {
    source: SankeyNodeDatum<NodeMeta>
    target: SankeyNodeDatum<NodeMeta>
    value: number
    color: string
    meta?: LinkMeta
    /** Position in the `links` prop and in `layout.links`; what `SankeyHighlight.linkIndices` names. */
    index: number
    y0: number
    y1: number
    width: number
}

export interface SankeyChartLayout<NodeMeta = unknown, LinkMeta = NodeMeta> {
    nodes: SankeyNodeDatum<NodeMeta>[]
    links: SankeyLinkDatum<NodeMeta, LinkMeta>[]
    columnCount: number
    /** Pixel x of each column's left edge, so overlays can place column headers. */
    columnX: number[]
    /** Total flow entering the graph: the summed value of the nodes with no incoming link.
     *  Tooltips report each node and link as a share of this. */
    total: number
    nodeWidth: number
}

export interface SankeyPlotBox {
    plotLeft: number
    plotTop: number
    plotWidth: number
    plotHeight: number
}

export interface ComputeSankeyLayoutOptions<NodeMeta, LinkMeta = NodeMeta> {
    nodes: readonly SankeyNodeInput<NodeMeta>[]
    links: readonly SankeyLinkInput<LinkMeta>[]
    plot: SankeyPlotBox
    nodeWidth: number
    nodePadding: number
    nodeAlign: SankeyNodeAlign
    preserveNodeOrder: boolean
    colorForLabel: (label: string) => string
    /** Applied to every color before it reaches the canvas, so `var(--…)` inputs resolve. */
    resolveColor: (color: string) => string
}

interface LayoutNodeProps {
    id: string
    label: string
    color: string
    meta?: unknown
    pinnedColumn?: number
    [key: string]: unknown
}

interface LayoutLinkProps {
    source: string | LayoutNodeProps
    target: string | LayoutNodeProps
    value: number
    color?: string
    meta?: unknown
    [key: string]: unknown
}

/** The layout allocates every column up to the highest pin, so one stray pin must not size it. */
export const MAX_SANKEY_COLUMN = 1000

const ALIGNMENTS = {
    left: sankeyLeft,
    right: sankeyRight,
    center: sankeyCenter,
    justify: sankeyJustify,
}

export function defaultValueFormatter(value: number): string {
    return value.toLocaleString()
}

export const EMPTY_SANKEY_LAYOUT: SankeyChartLayout<never> = {
    nodes: [],
    links: [],
    columnCount: 0,
    columnX: [],
    total: 0,
    nodeWidth: 0,
}

/** Nodes on the longest path through the graph, which is the column count the layout engine
 *  gives it. A cycle stops the count early; the engine reports the cycle itself. */
function longestPathLength(
    nodes: readonly SankeyNodeInput<unknown>[],
    links: readonly SankeyLinkInput<unknown>[]
): number {
    const incoming = new Map<string, number>(nodes.map((node) => [node.id, 0]))
    const outgoing = new Map<string, string[]>()
    for (const link of links) {
        incoming.set(link.target, (incoming.get(link.target) ?? 0) + 1)
        const targets = outgoing.get(link.source)
        if (targets) {
            targets.push(link.target)
        } else {
            outgoing.set(link.source, [link.target])
        }
    }
    const depth = new Map<string, number>()
    const ready = nodes.filter((node) => incoming.get(node.id) === 0).map((node) => node.id)
    let longest = 1
    for (let id = ready.pop(); id !== undefined; id = ready.pop()) {
        const next = (depth.get(id) ?? 1) + 1
        for (const target of outgoing.get(id) ?? []) {
            depth.set(target, Math.max(depth.get(target) ?? 1, next))
            longest = Math.max(longest, next)
            const remaining = (incoming.get(target) ?? 0) - 1
            incoming.set(target, remaining)
            if (remaining === 0) {
                ready.push(target)
            }
        }
    }
    return longest
}

/** Lays the graph out inside `plot`. Pure: safe to call from a memo or a test. Throws when a link
 *  names a missing node or the graph has a cycle, so a consumer bug surfaces through the chart's
 *  error boundary instead of drawing nothing. Returns `EMPTY_SANKEY_LAYOUT` when the graph has no
 *  flow (all link values are zero). */
export function computeSankeyLayout<NodeMeta = unknown, LinkMeta = NodeMeta>({
    nodes,
    links,
    plot,
    nodeWidth,
    nodePadding,
    nodeAlign,
    preserveNodeOrder,
    colorForLabel,
    resolveColor,
}: ComputeSankeyLayoutOptions<NodeMeta, LinkMeta>): SankeyChartLayout<NodeMeta, LinkMeta> {
    if (nodes.length === 0 || links.length === 0 || plot.plotWidth <= 0 || plot.plotHeight <= 0) {
        return EMPTY_SANKEY_LAYOUT as SankeyChartLayout<NodeMeta, LinkMeta>
    }

    const nodeIds = new Set<string>()
    for (const node of nodes) {
        if (nodeIds.has(node.id)) {
            throw new Error(`duplicate Sankey node id: ${node.id}`)
        }
        if (
            node.column !== undefined &&
            !(Number.isInteger(node.column) && node.column >= 0 && node.column <= MAX_SANKEY_COLUMN)
        ) {
            throw new Error(
                `Sankey node ${node.id} needs a whole column from 0 to ${MAX_SANKEY_COLUMN}, got ${node.column}`
            )
        }
        nodeIds.add(node.id)
    }
    for (const link of links) {
        if (!Number.isFinite(link.value) || link.value < 0) {
            throw new Error(`Sankey link value must be a finite non-negative number: ${link.value}`)
        }
        if (!nodeIds.has(link.source) || !nodeIds.has(link.target)) {
            throw new Error(`Sankey link refers to a missing node: ${link.source} -> ${link.target}`)
        }
    }
    if (!Number.isFinite(nodeWidth) || nodeWidth <= 0) {
        throw new Error(`Sankey nodeWidth must be a finite number above 0: ${nodeWidth}`)
    }
    if (!Number.isFinite(nodePadding) || nodePadding < 0) {
        throw new Error(`Sankey nodePadding must be a finite number of 0 or more: ${nodePadding}`)
    }
    const effectiveNodeWidth = Math.min(nodeWidth, plot.plotWidth / Math.max(1, longestPathLength(nodes, links) - 1))

    // The engine mutates its inputs, so hand it fresh objects.
    const engineNodes: LayoutNodeProps[] = nodes.map((node) => {
        const label = node.label ?? node.id
        return {
            id: node.id,
            label,
            color: resolveColor(node.color || colorForLabel(label)),
            meta: node.meta,
            pinnedColumn: node.column,
        }
    })
    const hasPinnedColumns = nodes.some((node) => node.column !== undefined)
    const engineLinks: LayoutLinkProps[] = links.map((link) => ({
        source: link.source,
        target: link.target,
        value: link.value,
        color: link.color,
        meta: link.meta,
    }))

    const graph = sankeyLayout<LayoutNodeProps, LayoutLinkProps>()
        .nodeId((node) => node.id)
        .nodeAlign(ALIGNMENTS[nodeAlign])
        .nodeColumn(hasPinnedColumns ? (node) => node.pinnedColumn : null)
        .nodeSort(preserveNodeOrder ? null : undefined)
        .nodeWidth(effectiveNodeWidth)
        .nodePadding(nodePadding)
        .extent([
            [plot.plotLeft, plot.plotTop],
            [plot.plotLeft + plot.plotWidth, plot.plotTop + plot.plotHeight],
        ])({ nodes: engineNodes, links: engineLinks })

    const datumByIndex = new Map<number, SankeyNodeDatum<NodeMeta>>()
    const outNodes = graph.nodes.map((node): SankeyNodeDatum<NodeMeta> => {
        const datum: SankeyNodeDatum<NodeMeta> = {
            id: node.id,
            label: node.label,
            color: node.color,
            meta: node.meta as NodeMeta | undefined,
            index: node.index,
            column: node.layer,
            value: node.value,
            x0: node.x0,
            x1: node.x1,
            y0: node.y0,
            y1: node.y1,
        }
        datumByIndex.set(node.index, datum)
        return datum
    })

    const outLinks = graph.links.map((link, index): SankeyLinkDatum<NodeMeta, LinkMeta> => {
        const source = datumByIndex.get(link.source.index)!
        const target = datumByIndex.get(link.target.index)!
        return {
            source,
            target,
            value: link.value,
            color: link.color ? resolveColor(link.color) : source.color,
            meta: link.meta as LinkMeta | undefined,
            index,
            y0: link.y0,
            y1: link.y1,
            width: link.width,
        }
    })

    const columnCount = graph.nodes.reduce((max, node) => Math.max(max, node.layer + 1), 0)
    // A pinned column can hold no node, so derive every column's x from the engine's spacing
    // rather than from the nodes that happen to land in it, and headers never read a hole.
    const columnStep = columnCount > 1 ? (plot.plotWidth - effectiveNodeWidth) / (columnCount - 1) : 0
    const columnX = Array.from({ length: columnCount }, (_, column) => plot.plotLeft + column * columnStep)

    const total = graph.nodes.filter((node) => node.targetLinks.length === 0).reduce((sum, node) => sum + node.value, 0)

    // Guard against all-zero flow: the layout engine produces NaN coordinates when total is 0
    if (total === 0) {
        return EMPTY_SANKEY_LAYOUT as SankeyChartLayout<NodeMeta, LinkMeta>
    }

    return { nodes: outNodes, links: outLinks, columnCount, columnX, total, nodeWidth: effectiveNodeWidth }
}

export type SankeyHit = { kind: 'node'; index: number } | { kind: 'link'; index: number }

/** Resolves what sits under the cursor: a node box first, then the nearest ribbon whose thickness
 *  covers the cursor, else `null`. Ribbons are the cubic curves the canvas draws (control points
 *  at the horizontal midpoint), so the test follows the painted shape exactly. */
export function sankeyHitAt(
    layout: SankeyChartLayout<unknown, unknown>,
    cursor: { x: number; y: number }
): SankeyHit | null {
    for (let i = 0; i < layout.nodes.length; i++) {
        const node = layout.nodes[i]
        const nodeHeight = Math.max(1, node.y1 - node.y0)
        const y0 = node.y0
        const y1 = y0 + nodeHeight
        if (cursor.x >= node.x0 && cursor.x <= node.x1 && cursor.y >= y0 && cursor.y <= y1) {
            return { kind: 'node', index: i }
        }
    }
    let best: { index: number; distance: number } | null = null
    for (let i = 0; i < layout.links.length; i++) {
        const link = layout.links[i]
        if (link.value === 0) {
            continue
        }
        const startX = link.source.x1
        const endX = link.target.x0
        if (cursor.x < startX || cursor.x > endX || endX <= startX) {
            continue
        }
        const halfWidth = Math.max(link.width, 1) / 2
        if (cursor.y < Math.min(link.y0, link.y1) - halfWidth || cursor.y > Math.max(link.y0, link.y1) + halfWidth) {
            continue
        }
        const distance = bezierDistance(startX, endX, link.y0, link.y1, cursor)
        if (distance <= halfWidth && (!best || distance < best.distance)) {
            best = { index: i, distance }
        }
    }
    return best ? { kind: 'link', index: best.index } : null
}

const MIN_CURVE_SAMPLES = 24
const MAX_CURVE_SAMPLES = 4096

function bezierDistance(x0: number, x1: number, y0: number, y1: number, cursor: { x: number; y: number }): number {
    // Each coordinate moves at most 1.5x its span per unit of t, so this count keeps adjacent
    // samples within 1px and a thin ribbon cannot fall between them.
    const samples = Math.min(
        MAX_CURVE_SAMPLES,
        Math.max(MIN_CURVE_SAMPLES, Math.ceil(1.5 * (Math.abs(x1 - x0) + Math.abs(y1 - y0))))
    )
    let best = Infinity
    for (let step = 0; step <= samples; step++) {
        const t = step / samples
        const distance = Math.hypot(bezierX(x0, x1, t) - cursor.x, bezierY(y0, y1, t) - cursor.y)
        best = Math.min(best, distance)
    }
    return best
}

/** x(t) of the ribbon centerline, with both control points at the horizontal midpoint. */
export function bezierX(x0: number, x1: number, t: number): number {
    const xm = (x0 + x1) / 2
    const u = 1 - t
    return u * u * u * x0 + 3 * u * u * t * xm + 3 * u * t * t * xm + t * t * t * x1
}

/** y(t) of the ribbon centerline: the control points share the end points' y, so the curve eases
 *  from `y0` to `y1`. */
export function bezierY(y0: number, y1: number, t: number): number {
    const u = 1 - t
    return u * u * u * y0 + 3 * u * u * t * y0 + 3 * u * t * t * y1 + t * t * t * y1
}

/** Encodes a hit into the single `hoverIndex` the shared draw loop expects: nodes first, then
 *  links offset by the node count. */
export function hitToHoverIndex(layout: SankeyChartLayout<unknown, unknown>, hit: SankeyHit | null): number {
    if (!hit) {
        return -1
    }
    return hit.kind === 'node' ? hit.index : layout.nodes.length + hit.index
}

export function hoverIndexToHit(layout: SankeyChartLayout<unknown, unknown>, hoverIndex: number): SankeyHit | null {
    if (hoverIndex < 0) {
        return null
    }
    if (hoverIndex < layout.nodes.length) {
        return { kind: 'node', index: hoverIndex }
    }
    const linkIndex = hoverIndex - layout.nodes.length
    return linkIndex < layout.links.length ? { kind: 'link', index: linkIndex } : null
}
