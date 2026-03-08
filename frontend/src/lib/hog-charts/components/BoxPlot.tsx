import { useMemo } from 'react'

import { buildBoxPlotConfig } from '../adapters'
import type { BoxPlotProps } from '../types'
import { ChartCanvas } from './ChartCanvas'

export function BoxPlot(props: BoxPlotProps): JSX.Element {
    const config = useMemo(() => buildBoxPlotConfig(props), [JSON.stringify(props)])
    return <ChartCanvas config={config} {...props} />
}
