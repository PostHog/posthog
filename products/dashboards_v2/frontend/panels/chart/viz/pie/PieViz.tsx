import { useMemo } from 'react'

import { PieChart } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { categoriesFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

export function PieViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const series = useMemo(() => categoriesFromFrames(frames), [frames])
    return <PieChart series={series} />
}
