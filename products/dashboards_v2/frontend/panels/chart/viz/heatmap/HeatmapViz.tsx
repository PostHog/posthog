import { useMemo } from 'react'

import { Heatmap } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { heatmapFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

export function HeatmapViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { xLabels, yLabels, cells } = useMemo(() => heatmapFromFrames(frames), [frames])
    return <Heatmap xLabels={xLabels} yLabels={yLabels} cells={cells} />
}
