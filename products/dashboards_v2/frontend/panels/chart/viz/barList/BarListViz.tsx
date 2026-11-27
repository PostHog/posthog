import { useMemo } from 'react'

import { BarList } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { categoriesFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

export function BarListViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const series = useMemo(() => categoriesFromFrames(frames).sort((a, b) => b.data[0] - a.data[0]), [frames])
    return <BarList series={series} />
}
