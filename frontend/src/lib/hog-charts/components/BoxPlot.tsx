import { useMemo } from 'react'

import { buildBoxPlotConfig } from '../adapter'
import type { BoxPlotProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

/** A box-and-whisker plot for distribution data. */
export function BoxPlot(props: BoxPlotProps): JSX.Element {
    const config = useMemo(() => buildBoxPlotConfig(props), [JSON.stringify(props)])
    return <ChartCanvas config={config} {...props} />
}
