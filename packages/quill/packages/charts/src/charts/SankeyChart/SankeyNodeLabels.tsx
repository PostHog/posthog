import React from 'react'

import { FONT_FAMILY, truncateToWidth } from '../../utils/text-measure'
import { useSankeyLayout } from './sankey-context'

const LABEL_FONT_SIZE = 11
const LABEL_FONT = `${LABEL_FONT_SIZE}px ${FONT_FAMILY}`
const LABEL_GAP = 6

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

/** One label per node, to the right of it; the last column's labels sit to its left so they stay
 *  inside the plot. Labels truncate to the free space before the next column. */
export function SankeyNodeLabels({ color, showValues, valueFormatter }: SankeyNodeLabelsProps): React.ReactElement {
    const { layout } = useSankeyLayout()
    const gap = layout.columnCount > 1 ? layout.columnX[1] - layout.columnX[0] - layout.nodeWidth : Infinity
    const maxWidth = gap - LABEL_GAP * 2

    return (
        <>
            {layout.nodes.map((node) => {
                const text = showValues ? `${node.label} ${valueFormatter(node.value)}` : node.label
                const last = node.column === layout.columnCount - 1 && layout.columnCount > 1
                const shown = truncateToWidth(text, isFinite(maxWidth) ? maxWidth : Infinity, LABEL_FONT)
                const style: React.CSSProperties = {
                    ...LABEL_STYLE_BASE,
                    color,
                    top: (node.y0 + node.y1) / 2,
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
