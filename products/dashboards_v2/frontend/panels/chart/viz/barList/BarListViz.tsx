import { useMemo } from 'react'

import { BarList } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { categoriesFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

// Rows past this are clipped by any tile, but would still be laid out and drawn.
const MAX_ROWS = 50

export function BarListViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const series = useMemo(
        () =>
            categoriesFromFrames(frames)
                .sort((a, b) => b.data[0] - a.data[0])
                .slice(0, MAX_ROWS),
        [frames]
    )
    return <BarList series={series} />
}
