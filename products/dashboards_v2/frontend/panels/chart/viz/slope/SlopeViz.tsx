import { useMemo } from 'react'

import { SlopeChart } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { slopeFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

export function SlopeViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { labels, series } = useMemo(() => slopeFromFrames(frames), [frames])
    return <SlopeChart labels={labels} series={series} />
}
