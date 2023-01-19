import { useRef, useEffect, useState } from 'react'
import { useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

import { pathsLogic } from 'scenes/paths/pathsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { PathNodeCard, PathNodeCardDataExploration, PathNodeCardProps } from './PathNodeCard'
import { renderPaths } from './renderPaths'
import type { PathNodeData } from './pathUtils'

import './Paths.scss'

const DEFAULT_PATHS_ID = 'default_paths'
export const HIDE_PATH_CARD_HEIGHT = 30
export const FALLBACK_CANVAS_WIDTH = 1000
const FALLBACK_CANVAS_HEIGHT = 0

export function PathsDataExploration(): JSX.Element {
    return <PathsComponent nodeCard={PathNodeCardDataExploration} />
}

export function Paths(): JSX.Element {
    return <PathsComponent nodeCard={PathNodeCard} />
}

type PathsComponentProps = {
    nodeCard: (props: PathNodeCardProps) => JSX.Element | null
}

export function PathsComponent({ nodeCard }: PathsComponentProps): JSX.Element {
    const canvasRef = useRef<HTMLDivElement>(null)
    const { width: canvasWidth = FALLBACK_CANVAS_WIDTH, height: canvasHeight = FALLBACK_CANVAS_HEIGHT } =
        useResizeObserver({ ref: canvasRef })
    const [nodeCards, setNodeCards] = useState<PathNodeData[]>([])

    const { insight, insightProps } = useValues(insightLogic)
    const { paths, resultsLoading: pathsLoading, filter, pathsError } = useValues(pathsLogic(insightProps))

    const id = `'${insight?.short_id || DEFAULT_PATHS_ID}'`

    useEffect(() => {
        setNodeCards([])

        const elements = document?.getElementById(id)?.querySelectorAll(`.Paths svg`)
        elements?.forEach((node) => node?.parentNode?.removeChild(node))

        renderPaths(canvasRef, canvasWidth, canvasHeight, paths, filter, setNodeCards)
    }, [paths, !pathsLoading, canvasWidth, canvasHeight])

    const NodeCard = nodeCard
    return (
        <div className="h-full w-full overflow-auto" id={id}>
            <div ref={canvasRef} className="Paths" data-attr="paths-viz">
                {!pathsLoading && paths && paths.nodes.length === 0 && !pathsError && <InsightEmptyState />}
                {!pathsError &&
                    nodeCards &&
                    nodeCards.map((node, idx) => <NodeCard key={idx} node={node} insightProps={insightProps} />)}
            </div>
        </div>
    )
}
