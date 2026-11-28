import { useMemo } from 'react'

import { BoxPlot } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { boxPlotFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

export function BoxPlotViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { labels, series } = useMemo(() => boxPlotFromFrames(frames), [frames])
    return <BoxPlot labels={labels} series={series} />
}
