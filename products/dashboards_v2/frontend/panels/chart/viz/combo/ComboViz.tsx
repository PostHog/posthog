import { useMemo } from 'react'

import { TimeSeriesComboChart } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { useTimeSeriesChart } from '../../data/useTimeSeriesChart'
import type { NoOptions } from '../../vizTypes'

export function ComboViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { labels, series, baseConfig } = useTimeSeriesChart(frames)
    // The first series reads as the total, so it draws as bars under the others.
    const mixed = useMemo(
        () => series.map((one, index) => ({ ...one, type: index === 0 ? 'bar' : 'line' }) as const),
        [series]
    )
    return <TimeSeriesComboChart series={mixed} labels={labels} config={baseConfig} />
}
