import './Paths.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelPathsFilter } from '~/queries/schema/schema-general'
import { shouldQueryBeAsync } from '~/queries/utils'

import { PathNodeCard } from './PathNodeCard'
import type { PathNodeData } from './pathUtils'
import { pathsDataLogic } from './pathsDataLogic'
import { renderPaths } from './renderPaths'

const DEFAULT_PATHS_ID = 'default_paths'
export const HIDE_PATH_CARD_HEIGHT = 30
export const FALLBACK_CANVAS_WIDTH = 1000
const FALLBACK_CANVAS_HEIGHT = 0

export function Paths(): JSX.Element {
    const canvasRef = useRef<HTMLDivElement>(null)
    const canvasContainerRef = useRef<HTMLDivElement>(null)
    const { width: canvasWidth = FALLBACK_CANVAS_WIDTH, height: canvasHeight = FALLBACK_CANVAS_HEIGHT } =
        useResizeObserver({ ref: canvasRef })
    const [nodeCards, setNodeCards] = useState<PathNodeData[]>([])

    const { insight, insightProps } = useValues(insightLogic)
    const { insightQuery, paths, pathsFilter, funnelPathsFilter, insightDataLoading, insightDataError, theme } =
        useValues(pathsDataLogic(insightProps))
    const { loadData } = useActions(insightDataLogic(insightProps))

    const id = `'${insight?.short_id || DEFAULT_PATHS_ID}'`

    useEffect(() => {
        setNodeCards([])

        // Remove the existing SVG canvas(es). The .Paths__canvas selector is crucial, as we have to be sure
        // we're only removing the Paths viz and not, for example, button icons.
        // Only remove canvases within this component's container
        const elements = canvasContainerRef.current?.querySelectorAll(`.Paths__canvas`)
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

        // Proper cleanup
        return () => {
            const elements = canvasContainerRef.current?.querySelectorAll(`.Paths__canvas`)
            elements?.forEach((node) => node?.parentNode?.removeChild(node))
        }
    }, [paths, insightDataLoading, canvasWidth, canvasHeight, theme, pathsFilter, funnelPathsFilter])

    if (insightDataError) {
        return (
            <InsightErrorState
                query={insightQuery}
                excludeDetail
                onRetry={() => {
                    loadData(shouldQueryBeAsync(insightQuery) ? 'force_async' : 'force_blocking')
                }}
            />
        )
    }

    return (
        <div className="h-full w-full overflow-auto" id={id} ref={canvasContainerRef}>
            <div
                ref={canvasRef}
                className="Paths"
                data-attr="paths-viz"
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--paths-node': theme?.['preset-1'] || '#000000',
                        '--paths-node-start-or-end': theme?.['preset-2'] || '#000000',
                        '--paths-link': theme?.['preset-1'] || '#000000',
                        '--paths-link-hover': theme?.['preset-2'] || '#000000',
                        '--paths-dropoff': 'rgba(220,53,69,0.7)',
                    } as React.CSSProperties
                }
            >
                {!insightDataLoading && paths && paths.nodes.length === 0 && !insightDataError && <InsightEmptyState />}
                {!insightDataError &&
                    nodeCards &&
                    nodeCards.map((node, idx) => (
                        <PathNodeCard key={idx} node={node} insightProps={insightProps} canvasHeight={canvasHeight} />
                    ))}
            </div>
        </div>
    )
}
