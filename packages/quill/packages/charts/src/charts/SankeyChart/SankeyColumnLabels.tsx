import React from 'react'

import { FONT_FAMILY, ELLIPSIS, measureLabelWidth } from '../../utils/text-measure'
import { useSankeyLayout } from './sankey-context'

const HEADER_FONT_SIZE = 10
const HEADER_FONT = `${HEADER_FONT_SIZE}px ${FONT_FAMILY}`
const HEADER_LETTER_SPACING = 0.04 * HEADER_FONT_SIZE
/** Space kept between two neighboring headers. */
const HEADER_GAP = 8

function headerWidth(text: string): number {
    return measureLabelWidth(text.toUpperCase(), HEADER_FONT) + text.length * HEADER_LETTER_SPACING
}

/** `label` shortened with an ellipsis to fit `maxWidth` as an uppercase, letter-spaced header. */
export function fitHeader(label: string, maxWidth: number): string {
    if (headerWidth(label) <= maxWidth) {
        return label
    }
    let end = label.length
    while (end > 0 && headerWidth(label.slice(0, end) + ELLIPSIS) > maxWidth) {
        end--
    }
    return end > 0 ? label.slice(0, end).trimEnd() + ELLIPSIS : ''
}

const LABEL_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    pointerEvents: 'none',
    top: 0,
    fontSize: HEADER_FONT_SIZE,
    lineHeight: 1.2,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    whiteSpace: 'nowrap',
}

export interface SankeyColumnLabelsProps {
    labels: string[]
    color: string
    /** Free space right of the last column, such as the margin reserved for `outside` labels. */
    trailingRoom?: number
}

/** Column headers over each node column. The first and last headers align to the outer node edge
 *  instead of centering, so they stay inside the chart. Extra labels beyond the column count are
 *  dropped, so a fixed stage list stays valid when the data has fewer stages. */
export function SankeyColumnLabels({ labels, color, trailingRoom = 0 }: SankeyColumnLabelsProps): React.ReactElement {
    const { layout } = useSankeyLayout()
    const lastColumn = layout.columnCount - 1
    // Each header owns the span halfway to its neighbors' node centers, so neighbors cannot run together.
    const step = layout.columnCount > 1 ? layout.columnX[1] - layout.columnX[0] : Infinity
    const middleWidth = step - HEADER_GAP
    const edgeWidth = layout.nodeWidth / 2 + step / 2 - HEADER_GAP / 2
    return (
        <>
            {Array.from({ length: layout.columnCount }, (_, column) => {
                const x = layout.columnX[column]
                const label = labels[column]
                if (!label || x === undefined) {
                    return null
                }
                // With room past the last column, its header starts over the nodes and runs into that room.
                const trailing = column === lastColumn && trailingRoom > 0
                let room = column === 0 || column === lastColumn ? edgeWidth : middleWidth
                if (trailing) {
                    room = layout.nodeWidth + trailingRoom
                }
                const shown = isFinite(room) ? fitHeader(label, room) : label
                let placement: React.CSSProperties
                if (column === 0 || trailing) {
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
                        {shown}
                    </div>
                )
            })}
        </>
    )
}
