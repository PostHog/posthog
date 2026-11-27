import { useMemo } from 'react'

import { SankeyChart } from '@posthog/quill-charts'

import type { DataFrame } from '../../../../query/queryTypes'
import { flowsFromFrames } from '../../data/frameShapes'
import type { NoOptions } from '../../vizTypes'

export function SankeyViz({ frames }: { frames: DataFrame[]; options: NoOptions }): JSX.Element {
    const { nodes, links } = useMemo(() => flowsFromFrames(frames), [frames])
    return <SankeyChart nodes={nodes} links={links} />
}
