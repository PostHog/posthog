import { useRef, useEffect, useState } from 'react'
import { useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

import { insightLogic } from 'scenes/insights/insightLogic'
import { pathsDataLogic } from './pathsDataLogic'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { PathNodeCard } from './PathNodeCard'
import { renderPaths } from './renderPaths'
import type { PathNodeData } from './pathUtils'

import './Paths.scss'

const DEFAULT_PATHS_ID = 'default_paths'
export const HIDE_PATH_CARD_HEIGHT = 30
export const FALLBACK_CANVAS_WIDTH = 1000
const FALLBACK_CANVAS_HEIGHT = 0

export function Paths(): JSX.Element {
    const canvasRef = useRef<HTMLDivElement>(null)
    const { width: canvasWidth = FALLBACK_CANVAS_WIDTH, height: canvasHeight = FALLBACK_CANVAS_HEIGHT } =
        useResizeObserver({ ref: canvasRef })
    const [nodeCards, setNodeCards] = useState<PathNodeData[]>([])

    const { insight, insightProps } = useValues(insightLogic)
    const { paths, pathsLoading, pathsError, pathsFilter } = useValues(pathsDataLogic(insightProps))

    const id = `'${insight?.short_id || DEFAULT_PATHS_ID}'`

    useEffect(() => {
        setNodeCards([])

        // Remove the existing SVG canvas(es). The .Paths__canvas selector is crucial, as we have to be sure
        // we're only removing the Paths viz and not, for example, button icons.
        const elements = document?.getElementById(id)?.querySelectorAll(`.Paths__canvas`)
        elements?.forEach((node) => node?.parentNode?.removeChild(node))

        renderPaths(canvasRef, canvasWidth, canvasHeight, paths, pathsFilter || {}, setNodeCards)
    }, [paths, !pathsLoading, canvasWidth, canvasHeight])

    return (
        <div className="h-full w-full overflow-auto" id={id}>
            <div ref={canvasRef} className="Paths" data-attr="paths-viz">
                {!pathsLoading && paths && paths.nodes.length === 0 && !pathsError && <InsightEmptyState />}
                {!pathsError &&
                    nodeCards &&
                    nodeCards.map((node, idx) => <PathNodeCard key={idx} node={node} insightProps={insightProps} />)}
            </div>
        </div>
    )
}
