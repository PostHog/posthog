import { useMemo } from 'react'

import { buildLineConfig } from '../adapters'
import type { LineProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

export function Line(props: LineProps): JSX.Element {
    const config = useMemo(
        () => buildLineConfig(props),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [
            props.data,
            props.labels,
            props.compare,
            props.stacked,
            props.cumulative,
            props.interpolation,
            props.isArea,
            props.fillOpacity,
            props.lineWidth,
            props.showDots,
            props.percentStacked,
            props.incompletePoints,
            props.hideXAxis,
            props.hideYAxis,
            props.crosshair,
            props.goalLines,
            props.annotations,
            props.showValues,
            props.showTrendLine,
            props.animate,
            props.theme,
            props.xAxis,
            props.yAxis,
            props.maxSeries,
        ]
    )
    return <ChartCanvas config={config} {...props} />
}
