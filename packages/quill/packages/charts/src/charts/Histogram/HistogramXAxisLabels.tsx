import React from 'react'

import { useChartLayout } from '../../core/chart-context'
import { TICK_GAP } from '../../core/y-axis-gutters'
import { readHistogramLayout } from './histogram-scales'

// Matches the base chart's fallback, so a theme without an axis color renders both axes alike.
const DEFAULT_AXIS_COLOR = 'rgba(0, 0, 0, 0.5)'

const TICK_STYLE: React.CSSProperties = {
    position: 'absolute',
    fontSize: 12,
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
    transform: 'translateX(-50%)',
}

/** Numeric bin-edge ticks in place of the base chart's one-label-per-category layer, under the
 *  same `data-attr` so the test accessor's `xTicks()` reads them. */
export function HistogramXAxisLabels(): React.ReactElement | null {
    const { scales, dimensions, theme } = useChartLayout()
    const ticks = readHistogramLayout(scales)?.xTicks
    if (!ticks?.length) {
        return null
    }
    const top = dimensions.plotTop + dimensions.plotHeight + TICK_GAP
    return (
        <>
            {ticks.map(({ value, text, x }) => (
                <div
                    key={value}
                    data-attr="hog-chart-axis-tick-x"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ ...TICK_STYLE, left: x, top, color: theme.axisColor ?? DEFAULT_AXIS_COLOR }}
                >
                    {text}
                </div>
            ))}
        </>
    )
}
