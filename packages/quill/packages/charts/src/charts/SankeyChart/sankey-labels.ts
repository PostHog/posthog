import { FONT_FAMILY, measureLabelWidth, truncateToWidth } from '../../utils/text-measure'
import type { SankeyChartLayout, SankeyLinkInput, SankeyNodeDatum, SankeyNodeInput } from './sankey-data'

export const LABEL_FONT_SIZE = 11
export const LABEL_FONT = `${LABEL_FONT_SIZE}px ${FONT_FAMILY}`
export const LABEL_GAP = 6
/** Vertical room one label needs; two label centers closer than this overlap. */
export const LABEL_LINE_HEIGHT = LABEL_FONT_SIZE * 1.2
/** Widest margin `lastColumnLabels: 'outside'` reserves, so long outcome names cannot squeeze the plot. */
const MAX_OUTSIDE_LABEL_WIDTH = 160

/** Where the last column's labels go: `inside` sits them left of the nodes, over the ribbons;
 *  `outside` sits them right of the nodes in a margin reserved for them. */
export type SankeyLastColumnLabels = 'inside' | 'outside'

/** A node label as drawn: its full and truncated text and the box it occupies, in chart pixels. */
export interface SankeyLabelBox {
    /** Index of the node in `layout.nodes`. */
    index: number
    text: string
    shown: string
    side: 'left' | 'right'
    x0: number
    x1: number
    y0: number
    y1: number
}

export interface SankeyLabelOptions {
    showValues: boolean
    valueFormatter: (value: number) => string
    lastColumnLabels: SankeyLastColumnLabels
    /** Room right of the last column for `outside` labels. */
    outsideWidth: number
}

const centerY = (node: SankeyNodeDatum): number => (node.y0 + node.y1) / 2

/** Nodes whose label fits without covering a neighbor's. Thin nodes stacked in one column would
 *  print on top of each other, so the larger flow keeps its label and the tooltip still names the
 *  rest. */
export function labeledNodes(nodes: SankeyNodeDatum[]): Set<SankeyNodeDatum> {
    const kept = new Set<SankeyNodeDatum>()
    const byColumn = new Map<number, SankeyNodeDatum[]>()
    for (const node of nodes) {
        const column = byColumn.get(node.column)
        if (column) {
            column.push(node)
        } else {
            byColumn.set(node.column, [node])
        }
    }
    for (const column of byColumn.values()) {
        const placed: number[] = []
        for (const node of [...column].sort((a, b) => b.value - a.value)) {
            const y = centerY(node)
            if (placed.every((other) => Math.abs(other - y) >= LABEL_LINE_HEIGHT)) {
                placed.push(y)
                kept.add(node)
            }
        }
    }
    return kept
}

/** Labels in the last two columns that share the gap between those columns at about the same
 *  height. The penultimate column's labels run right and the last column's run left, so each of
 *  these gets half the gap. */
export function labelsSharingLastGap(shown: Set<SankeyNodeDatum>, columnCount: number): Set<SankeyNodeDatum> {
    const crowded = new Set<SankeyNodeDatum>()
    if (columnCount < 2) {
        return crowded
    }
    const nodes = [...shown]
    const left = nodes.filter((node) => node.column === columnCount - 2)
    const right = nodes.filter((node) => node.column === columnCount - 1)
    for (const a of left) {
        for (const b of right) {
            if (Math.abs(centerY(a) - centerY(b)) < LABEL_LINE_HEIGHT) {
                crowded.add(a)
                crowded.add(b)
            }
        }
    }
    return crowded
}

/** The box of every label the chart draws. Labels sit right of their node and truncate to the free
 *  space before the next column; the last column's labels sit inside, left of the nodes, or
 *  outside in the reserved margin. Rendering and hit testing both read these boxes, so hovering a
 *  label hovers its node. */
export function sankeyLabelBoxes(
    layout: SankeyChartLayout<unknown, unknown>,
    { showValues, valueFormatter, lastColumnLabels, outsideWidth }: SankeyLabelOptions
): SankeyLabelBox[] {
    const columnGap = layout.columnX.length > 1 ? layout.columnX[1] - layout.columnX[0] - layout.nodeWidth : Infinity
    const maxWidth = Math.max(0, columnGap - LABEL_GAP * 2)
    const sharedMaxWidth = Math.max(0, (columnGap - LABEL_GAP * 3) / 2)
    const shownNodes = labeledNodes(layout.nodes)
    const crowded = lastColumnLabels === 'inside' ? labelsSharingLastGap(shownNodes, layout.columnCount) : new Set()
    const lastColumn = layout.columnCount > 1 ? layout.columnCount - 1 : -1

    const boxes: SankeyLabelBox[] = []
    layout.nodes.forEach((node, index) => {
        if (!shownNodes.has(node)) {
            return
        }
        const text = showValues ? `${node.label} ${valueFormatter(node.value)}` : node.label
        const inLastColumn = node.column === lastColumn
        let room = crowded.has(node) ? sharedMaxWidth : maxWidth
        if (inLastColumn && lastColumnLabels === 'outside') {
            room = Math.max(0, outsideWidth - LABEL_GAP)
        }
        const shown = truncateToWidth(text, isFinite(room) ? room : 0, LABEL_FONT)
        const width = measureLabelWidth(shown, LABEL_FONT)
        const side = inLastColumn && lastColumnLabels === 'inside' ? 'left' : 'right'
        const x0 = side === 'right' ? node.x1 + LABEL_GAP : node.x0 - LABEL_GAP - width
        const y = centerY(node)
        boxes.push({
            index,
            text,
            shown,
            side,
            x0,
            x1: x0 + width,
            y0: y - LABEL_LINE_HEIGHT / 2,
            y1: y + LABEL_LINE_HEIGHT / 2,
        })
    })
    return boxes
}

/** Width to reserve right of the plot for `outside` labels: the widest sink-node label, capped.
 *  Measured from the inputs because the margin must be known before the layout runs. */
export function outsideLabelWidth(
    nodes: readonly SankeyNodeInput<unknown>[],
    links: readonly SankeyLinkInput<unknown>[],
    showValues: boolean,
    valueFormatter: (value: number) => string
): number {
    const inflow = new Map<string, number>()
    const hasOutgoing = new Set<string>()
    for (const link of links) {
        hasOutgoing.add(link.source)
        inflow.set(link.target, (inflow.get(link.target) ?? 0) + link.value)
    }
    let widest = 0
    for (const node of nodes) {
        if (hasOutgoing.has(node.id)) {
            continue
        }
        const label = node.label ?? node.id
        const text = showValues ? `${label} ${valueFormatter(inflow.get(node.id) ?? 0)}` : label
        widest = Math.max(widest, measureLabelWidth(text, LABEL_FONT))
    }
    return widest === 0 ? 0 : Math.min(MAX_OUTSIDE_LABEL_WIDTH, Math.ceil(widest) + LABEL_GAP)
}
