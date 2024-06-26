import './Paths.scss'

import { useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useEffect, useRef, useState } from 'react'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelPathsFilter } from '~/queries/schema'

import { PathNodeCard } from './PathNodeCard'
import { pathsDataLogic } from './pathsDataLogic'
import type { PathNodeData } from './pathUtils'
import { renderPaths } from './renderPaths'

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
    const { insightQuery, paths, pathsFilter, funnelPathsFilter, insightDataLoading, insightDataError } = useValues(
        pathsDataLogic(insightProps)
    )

    const id = `'${insight?.short_id || DEFAULT_PATHS_ID}'`

    useEffect(() => {
        setNodeCards([])

        // Remove the existing SVG canvas(es). The .Paths__canvas selector is crucial, as we have to be sure
        // we're only removing the Paths viz and not, for example, button icons.
        const elements = document?.getElementById(id)?.querySelectorAll(`.Paths__canvas`)
        elements?.forEach((node) => node?.parentNode?.removeChild(node))

        renderPaths(
            canvasRef,
            canvasWidth,
            canvasHeight,
            paths,
            pathsFilter || {},
            funnelPathsFilter || ({} as FunnelPathsFilter),
            setNodeCards
        )
    }, [paths, !insightDataLoading, canvasWidth, canvasHeight])

    if (insightDataError) {
        return <InsightErrorState query={insightQuery} excludeDetail />
    }

    return (
        <div className="h-full w-full overflow-auto" id={id}>
            <div ref={canvasRef} className="Paths" data-attr="paths-viz">
                {!insightDataLoading && paths && paths.nodes.length === 0 && !insightDataError && <InsightEmptyState />}
                {!insightDataError &&
                    nodeCards &&
                    nodeCards.map((node, idx) => <PathNodeCard key={idx} node={node} insightProps={insightProps} />)}
            </div>
        </div>
    )
}
