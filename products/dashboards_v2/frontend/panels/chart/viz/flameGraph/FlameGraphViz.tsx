import { useMemo } from 'react'

import { FlameGraph } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { flameFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

export function FlameGraphViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const data = useMemo(() => flameFromFrames(frames), [frames])
    return <FlameGraph data={data} />
}
