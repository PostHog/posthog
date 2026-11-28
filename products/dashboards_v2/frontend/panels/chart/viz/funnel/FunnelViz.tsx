import { useMemo } from 'react'

import { FunnelChart, funnelFromCounts } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { categoriesFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

export function FunnelViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { steps, series } = useMemo(
        () =>
            funnelFromCounts(categoriesFromFrames(frames).map((step) => ({ label: step.label, count: step.data[0] }))),
        [frames]
    )
    return <FunnelChart steps={steps} series={series} />
}
