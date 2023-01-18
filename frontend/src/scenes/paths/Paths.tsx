import { useRef, useEffect, useState } from 'react'
import { useValues } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import './Paths.scss'
import { PathNodeData } from './pathUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { PathItemCard } from './PathItemCard'
import { renderPaths } from './renderPaths'

const DEFAULT_PATHS_ID = 'default_paths'
export const HIDE_PATH_CARD_HEIGHT = 30
export const FALLBACK_CANVAS_WIDTH = 1000
const FALLBACK_CANVAS_HEIGHT = 0

export function Paths(): JSX.Element {
    const canvasRef = useRef<HTMLDivElement>(null)
    const { width: canvasWidth = FALLBACK_CANVAS_WIDTH, height: canvasHeight = FALLBACK_CANVAS_HEIGHT } =
        useResizeObserver({ ref: canvasRef })
    const [pathItemCards, setPathItemCards] = useState<PathNodeData[]>([])

    const { insight, insightProps } = useValues(insightLogic)
    const { paths, resultsLoading: pathsLoading, filter, pathsError } = useValues(pathsLogic(insightProps))

    const id = `'${insight?.short_id || DEFAULT_PATHS_ID}'`

    useEffect(() => {
        setPathItemCards([])

        const elements = document?.getElementById(id)?.querySelectorAll(`.paths svg`)
        elements?.forEach((node) => node?.parentNode?.removeChild(node))

        renderPaths(canvasRef, canvasWidth, canvasHeight, paths, filter, setPathItemCards)
    }, [paths, !pathsLoading, canvasWidth, canvasHeight])

    return (
        <div className="paths-container" id={id}>
            <div ref={canvasRef} className="paths" data-attr="paths-viz">
                {!pathsLoading && paths && paths.nodes.length === 0 && !pathsError && <InsightEmptyState />}
                {!pathsError &&
                    pathItemCards &&
                    pathItemCards.map((node, idx) => (
                        <PathItemCard key={idx} node={node} insightProps={insightProps} />
                    ))}
            </div>
        </div>
    )
}
