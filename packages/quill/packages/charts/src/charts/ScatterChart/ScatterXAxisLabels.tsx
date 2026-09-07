import React from 'react'

import { useChartLayout } from '../../core/chart-context'
import { TICK_GAP } from '../../core/y-axis-gutters'
import { readScatterLayout } from './scatter-layout'

// Matches the base chart's fallback, so a theme without an axis color renders both axes alike.
const DEFAULT_AXIS_COLOR = 'rgba(0, 0, 0, 0.5)'

const TICK_STYLE: React.CSSProperties = {
    position: 'absolute',
    fontSize: 12,
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
    transform: 'translateX(-50%)',
}

/** Stands in for the base chart's one-label-per-category x-axis layer, carrying the same
 *  `data-attr` so test accessors read either chart alike. */
export function ScatterXAxisLabels(): React.ReactElement | null {
    const { scales, dimensions, theme } = useChartLayout()
    const ticks = readScatterLayout(scales)?.xTicks

    if (!ticks?.length) {
        return null
    }

    const top = dimensions.plotTop + dimensions.plotHeight + TICK_GAP
    return (
        <>
            {ticks.map(({ tick, text, x }) => (
                <div
                    key={tick}
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
