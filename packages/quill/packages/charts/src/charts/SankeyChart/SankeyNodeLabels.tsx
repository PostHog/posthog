import React from 'react'

import { LABEL_FONT_SIZE } from './sankey-labels'
import type { SankeyLabelBox } from './sankey-labels'

const LABEL_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    pointerEvents: 'none',
    fontSize: LABEL_FONT_SIZE,
    lineHeight: 1.2,
    whiteSpace: 'nowrap',
    transform: 'translateY(-50%)',
}

export function TruncatedText({ text, shown }: { text: string; shown: string }): React.ReactElement {
    if (shown === text) {
        return <>{text}</>
    }
    return (
        <>
            <span aria-hidden="true">{shown}</span>
            <span className="sr-only">{text}</span>
        </>
    )
}

export interface SankeyNodeLabelsProps {
    boxes: SankeyLabelBox[]
    color: string
}

/** Draws the labels `sankeyLabelBoxes` placed. The chart's hit test reads the same boxes, so the
 *  pointer passes through a label to the chart and hovering it shows its node's tooltip. */
export function SankeyNodeLabels({ boxes, color }: SankeyNodeLabelsProps): React.ReactElement {
    return (
        <>
            {boxes.map((box) => (
                <div
                    key={box.index}
                    data-attr="hog-chart-sankey-node-label"
                    style={{
                        ...LABEL_STYLE_BASE,
                        color,
                        top: (box.y0 + box.y1) / 2,
                        ...(box.side === 'right' ? { left: box.x0 } : { right: `calc(100% - ${box.x1}px)` }),
                    }}
                >
                    <TruncatedText text={box.text} shown={box.shown} />
                </div>
            ))}
        </>
    )
}
