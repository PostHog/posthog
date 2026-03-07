import { useMemo } from 'react'

import { buildLineConfig } from '../adapter'
import type { LineProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

/** A line chart for time-series data. */
export function Line(props: LineProps): JSX.Element {
    const config = useMemo(() => buildLineConfig(props), [JSON.stringify(props)])
    return <ChartCanvas config={config} {...props} />
}
