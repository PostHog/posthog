import React from 'react'

import { useSankeyLayout } from './sankey-context'

const LABEL_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    pointerEvents: 'none',
    top: 0,
    fontSize: 10,
    lineHeight: 1.2,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    whiteSpace: 'nowrap',
}

export interface SankeyColumnLabelsProps {
    labels: string[]
    color: string
}

/** Column headers over each node column. The first and last headers align to the outer node edge
 *  instead of centering, so they stay inside the chart. Extra labels beyond the column count are
 *  dropped, so a fixed stage list stays valid when the data has fewer stages. */
export function SankeyColumnLabels({ labels, color }: SankeyColumnLabelsProps): React.ReactElement {
    const { layout } = useSankeyLayout()
    const lastColumn = layout.columnCount - 1
    return (
        <>
            {layout.columnX.map((x, column) => {
                const label = labels[column]
                if (!label) {
                    return null
                }
                let placement: React.CSSProperties
                if (column === 0) {
                    placement = { left: x }
                } else if (column === lastColumn) {
                    placement = { right: `calc(100% - ${x + layout.nodeWidth}px)` }
                } else {
                    placement = { left: x + layout.nodeWidth / 2, transform: 'translateX(-50%)' }
                }
                return (
                    <div
                        key={column}
                        data-attr="hog-chart-sankey-column-label"
                        style={{ ...LABEL_STYLE_BASE, ...placement, color }}
                    >
                        {label}
                    </div>
                )
            })}
        </>
    )
}
