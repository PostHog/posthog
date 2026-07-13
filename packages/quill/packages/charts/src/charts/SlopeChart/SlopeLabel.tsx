import React from 'react'

import { FONT_FAMILY } from '../../utils/text-measure'
import type { SlopeSide } from './slope-data'

export const SLOPE_LABEL_FONT_SIZE = 12
const SLOPE_LABEL_FONT_WEIGHT = 600
/** The font slope labels render and measure with — keeps rendering and width measurement in step. */
export const SLOPE_LABEL_FONT = `${SLOPE_LABEL_FONT_WEIGHT} ${SLOPE_LABEL_FONT_SIZE}px ${FONT_FAMILY}`

export interface SlopeLabelProps {
    x: number
    y: number
    /** CSS transform anchoring the label relative to its `(x, y)` point. */
    transform: string
    color: string
    text: string
    dataAttr: string
    side?: SlopeSide
}

/** A single non-interactive slope label: series-colored text positioned absolutely at `(x, y)` and
 *  offset by `transform`. Shared by the value-label columns and the end-anchored series names. */
export function SlopeLabel({ x, y, transform, color, text, dataAttr, side }: SlopeLabelProps): React.ReactElement {
    return (
        <div
            data-attr={dataAttr}
            data-slope-side={side}
            style={{
                position: 'absolute',
                left: Math.round(x),
                top: Math.round(y),
                transform,
                color,
                fontSize: SLOPE_LABEL_FONT_SIZE,
                fontWeight: SLOPE_LABEL_FONT_WEIGHT,
                lineHeight: 1,
                whiteSpace: 'nowrap',
                pointerEvents: 'none',
            }}
        >
            {text}
        </div>
    )
}
