import React, { useMemo } from 'react'

import { FONT_FAMILY, truncateToWidth } from '../../utils/text-measure'
import { useSankeyLayout } from './sankey-context'
import type { SankeyNodeDatum } from './sankey-data'

const LABEL_FONT_SIZE = 11
const LABEL_FONT = `${LABEL_FONT_SIZE}px ${FONT_FAMILY}`
const LABEL_GAP = 6
/** Vertical room one label needs; two label centers closer than this overlap. */
const LABEL_LINE_HEIGHT = LABEL_FONT_SIZE * 1.2

const LABEL_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    pointerEvents: 'none',
    fontSize: LABEL_FONT_SIZE,
    lineHeight: 1.2,
    whiteSpace: 'nowrap',
    transform: 'translateY(-50%)',
}

export interface SankeyNodeLabelsProps {
    color: string
    showValues: boolean
    valueFormatter: (value: number) => string
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

/** One label per node, to the right of it; the last column's labels sit to its left so they stay
 *  inside the plot. Labels truncate to the free space before the next column. */
export function SankeyNodeLabels({ color, showValues, valueFormatter }: SankeyNodeLabelsProps): React.ReactElement {
    const { layout } = useSankeyLayout()
    const occupiedColumns = layout.columnX.filter((x): x is number => Number.isFinite(x))
    const gap = occupiedColumns.length > 1 ? occupiedColumns[1] - occupiedColumns[0] - layout.nodeWidth : Infinity
    const maxWidth = Math.max(0, gap - LABEL_GAP * 2)
    const sharedMaxWidth = Math.max(0, (gap - LABEL_GAP * 3) / 2)
    const shownNodes = useMemo(() => labeledNodes(layout.nodes), [layout.nodes])
    const crowdedNodes = useMemo(
        () => labelsSharingLastGap(shownNodes, layout.columnCount),
        [shownNodes, layout.columnCount]
    )

    return (
        <>
            {layout.nodes.map((node) => {
                if (!shownNodes.has(node)) {
                    return null
                }
                const text = showValues ? `${node.label} ${valueFormatter(node.value)}` : node.label
                const last = node.column === layout.columnCount - 1 && layout.columnCount > 1
                const shown = truncateToWidth(text, crowdedNodes.has(node) ? sharedMaxWidth : maxWidth, LABEL_FONT)
                const style: React.CSSProperties = {
                    ...LABEL_STYLE_BASE,
                    color,
                    top: centerY(node),
                    ...(last ? { right: `calc(100% - ${node.x0 - LABEL_GAP}px)` } : { left: node.x1 + LABEL_GAP }),
                }
                return (
                    <div key={node.id} data-attr="hog-chart-sankey-node-label" title={text} style={style}>
                        {shown}
                    </div>
                )
            })}
        </>
    )
}
