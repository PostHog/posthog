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

/** Numeric x-axis tick labels for {@link ScatterChart}.
 *
 *  The base chart's x-axis layer renders one label per category, which a continuous x axis has
 *  none of — so the chart feeds that layer nulls and this overlay draws the axis instead. The
 *  ticks are resolved in `createScales`, so the labels, the grid lines, and the tick marks are the
 *  same set by construction. It stays a DOM overlay (rather than canvas text) so it shares the
 *  library's overlay/canvas split, and its `data-attr` matches the base x ticks so test accessors
 *  read either chart the same way. */
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
