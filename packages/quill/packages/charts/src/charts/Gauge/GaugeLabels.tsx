import React from 'react'

import { GAUGE_VALUE_FONT_WEIGHT } from './gauge-layout'
import type { GaugeTextBlock } from './gauge-layout'

export interface GaugeEndLabel {
    text: string
    x: number
}

export interface GaugeEnds {
    min: GaugeEndLabel
    max: GaugeEndLabel
    top: number
    fontSize: number
}

interface GaugeLabelsProps {
    text: GaugeTextBlock | null
    ends: GaugeEnds | null
    /** The value is missing, so it reads muted at normal weight. */
    empty: boolean
    valueColor: string
    mutedColor: string | undefined
}

const TEXT_BASE_STYLE: React.CSSProperties = {
    position: 'absolute',
    transform: 'translate(-50%, -50%)',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    lineHeight: 1.2,
    textAlign: 'center',
    pointerEvents: 'none',
}

const MUTED_STYLE: React.CSSProperties = { opacity: 0.65 }

export function GaugeLabels({ text, ends, empty, valueColor, mutedColor }: GaugeLabelsProps): React.ReactElement {
    const mutedStyle = mutedColor ? { color: mutedColor } : MUTED_STYLE
    return (
        <>
            {text ? (
                <div
                    aria-hidden="true"
                    data-attr="hog-chart-gauge-value"
                    title={text.value.text}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        ...TEXT_BASE_STYLE,
                        left: text.value.x,
                        top: text.value.y,
                        maxWidth: text.value.maxWidth,
                        fontSize: text.value.fontSize,
                        fontWeight: empty ? 400 : GAUGE_VALUE_FONT_WEIGHT,
                        lineHeight: 1.1,
                        ...(empty ? mutedStyle : { color: valueColor }),
                    }}
                >
                    {text.value.text}
                </div>
            ) : null}
            {text?.label ? (
                <div
                    aria-hidden="true"
                    data-attr="hog-chart-gauge-label"
                    title={text.label.text}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        ...TEXT_BASE_STYLE,
                        ...mutedStyle,
                        left: text.label.x,
                        top: text.label.y,
                        maxWidth: text.label.maxWidth,
                        fontSize: text.label.fontSize,
                    }}
                >
                    {text.label.text}
                </div>
            ) : null}
            {ends
                ? (['min', 'max'] as const).map((end) => (
                      <div
                          key={end}
                          aria-hidden="true"
                          data-attr={`hog-chart-gauge-${end}`}
                          // eslint-disable-next-line react/forbid-dom-props
                          style={{
                              ...TEXT_BASE_STYLE,
                              ...mutedStyle,
                              transform: 'translate(-50%, 0)',
                              left: ends[end].x,
                              top: ends.top,
                              fontSize: ends.fontSize,
                              fontVariantNumeric: 'tabular-nums',
                          }}
                      >
                          {ends[end].text}
                      </div>
                  ))
                : null}
        </>
    )
}
