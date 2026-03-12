import { useMemo } from 'react'

import { buildLineConfig } from '../adapters'
import type { LineProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

export function Line(props: LineProps): JSX.Element {
    const config = useMemo(
        () => buildLineConfig(props),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [
            props.series,
            props.compare,
            props.options,
            props.goalLines,
            props.annotations,
            props.theme,
            props.xAxis,
            props.yAxis,
            props.interval,
        ]
    )
    return <ChartCanvas config={config} {...props} />
}
