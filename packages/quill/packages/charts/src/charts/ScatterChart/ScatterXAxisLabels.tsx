import React, { useMemo } from 'react'

import { useChartLayout } from '../../core/chart-context'
import { autoFormatterFor } from '../../core/scales'
import { TICK_GAP } from '../../core/y-axis-gutters'
import { computeVisibleValueTicks } from '../../overlays/AxisLabels'
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

export interface ScatterXAxisLabelsProps {
    /** Format a tick value. Defaults to the shared auto-precision numeric formatter. */
    tickFormatter?: (value: number) => string
}

/** Numeric x-axis tick labels for {@link ScatterChart}.
 *
 *  The base chart's x-axis layer renders one label per category, which a continuous x axis has
 *  none of — so the chart feeds that layer nulls and this overlay draws the axis instead, reusing
 *  the same value-tick collision pass a horizontal bar chart's value axis uses. It stays a DOM
 *  overlay (rather than canvas text) so it shares the library's overlay/canvas split, and its
 *  `data-attr` matches the base x ticks so test accessors read either chart the same way. */
export function ScatterXAxisLabels({ tickFormatter }: ScatterXAxisLabelsProps): React.ReactElement | null {
    const { scales, dimensions, theme } = useChartLayout()
    const layout = readScatterLayout(scales)
    const ticks = layout?.xTicks
    const xScale = layout?.xScale

    const visibleTicks = useMemo(
        () =>
            ticks && xScale ? computeVisibleValueTicks(ticks, xScale, tickFormatter ?? autoFormatterFor(ticks)) : [],
        [ticks, xScale, tickFormatter]
    )

    if (visibleTicks.length === 0) {
        return null
    }

    const top = dimensions.plotTop + dimensions.plotHeight + TICK_GAP
    return (
        <>
            {visibleTicks.map(({ tick, text, x }) => (
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
