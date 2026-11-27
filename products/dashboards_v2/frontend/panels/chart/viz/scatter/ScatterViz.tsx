import { useMemo } from 'react'

import { ScatterChart, type ScatterChartConfig } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { scatterFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

const TIME_AXIS: ScatterChartConfig = { xAxis: { tickFormatter: (ms) => new Date(ms).toISOString().slice(0, 10) } }

export function ScatterViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { series, overTime } = useMemo(() => scatterFromFrames(frames), [frames])
    return <ScatterChart series={series} config={overTime ? TIME_AXIS : undefined} />
}
