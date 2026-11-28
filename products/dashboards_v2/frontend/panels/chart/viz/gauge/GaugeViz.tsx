import { Gauge } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { latestValue } from '../../data/frameShapes'
import type { GaugeOptions } from './gaugeSpec'

export function GaugeViz({ frames, options }: { frames: DataFrame[]; options: GaugeOptions }): JSX.Element {
    return <Gauge value={latestValue(frames)} min={options.min} max={options.max} />
}
