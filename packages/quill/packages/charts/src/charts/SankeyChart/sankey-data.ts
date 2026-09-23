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
     *  the graph's edges — a link whose target column is at or before its source's draws backwards. */
    column?: number
}

/** A directed flow from `source` to `target` (both node ids). The graph must be acyclic. */
export interface SankeyLinkInput<Meta = unknown> {
    source: string
    target: string
    /** Flow magnitude. Drives the ribbon width and the node heights. */
    value: number
    /** CSS color for the ribbon. Defaults to the source node's color. */
    color?: string
    /** Consumer data handed back through tooltips and click handlers. */
    meta?: Meta
}

/** How nodes spread across columns when a flow ends early. Mirrors d3-sankey's alignments. */
export type SankeyNodeAlign = 'left' | 'right' | 'center' | 'justify'

/** A laid-out node: the input plus its pixel box, column, and total flow. */
export interface SankeyNodeDatum<Meta = unknown> {
    id: string
    label: string
    color: string
    meta?: Meta
    /** Position in the `nodes` prop and in `layout.nodes`. */
    index: number
    /** Zero-based column, left to right. */
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
    /** Number of columns the nodes occupy. */
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
    /** Keep the input order of nodes within a column instead of sorting by flow position. */
    preserveNodeOrder: boolean
    /** Resolves a node's fill when it sets no `color`. Receives the node's label. */
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
        .nodeWidth(nodeWidth)
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

    const columnCount = Math.max(0, ...graph.nodes.map((node) => node.layer + 1))
    const columnX: number[] = []
    for (const node of graph.nodes) {
        columnX[node.layer] = node.x0
    }

    const total = graph.nodes.filter((node) => node.targetLinks.length === 0).reduce((sum, node) => sum + node.value, 0)

    // Guard against all-zero flow: the layout engine produces NaN coordinates when total is 0
    if (total === 0) {
        return EMPTY_SANKEY_LAYOUT as SankeyChartLayout<NodeMeta, LinkMeta>
    }

    return { nodes: outNodes, links: outLinks, columnCount, columnX, total, nodeWidth }
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
        const startX = link.source.x1
        const endX = link.target.x0
        if (cursor.x < startX || cursor.x > endX || endX <= startX) {
            continue
        }
        const t = solveBezierT(startX, endX, cursor.x)
        const centerY = bezierY(link.y0, link.y1, t)
        const distance = Math.abs(cursor.y - centerY)
        if (distance <= Math.max(link.width, 1) / 2 && (!best || distance < best.distance)) {
            best = { index: i, distance }
        }
    }
    return best ? { kind: 'link', index: best.index } : null
}

/** x(t) of the ribbon centerline, with both control points at the horizontal midpoint. */
function bezierX(x0: number, x1: number, t: number): number {
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

/** Inverts `bezierX` for a cursor x. `x(t)` is monotonic on [0, 1], so bisection converges. */
function solveBezierT(x0: number, x1: number, x: number): number {
    let lo = 0
    let hi = 1
    for (let i = 0; i < 24; i++) {
        const mid = (lo + hi) / 2
        if (bezierX(x0, x1, mid) < x) {
            lo = mid
        } else {
            hi = mid
        }
    }
    return (lo + hi) / 2
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
