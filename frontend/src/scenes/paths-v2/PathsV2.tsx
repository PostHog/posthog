import './Paths.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { lightenDarkenColor } from 'lib/utils'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelPathsFilter } from '~/queries/schema/schema-general'
import { shouldQueryBeAsync } from '~/queries/utils'

import { PathNodeLabel } from './PathNodeLabel'
import type { PathNodeData } from './pathUtils'
import { pathsDataLogic } from './pathsDataLogic'
import { renderPaths } from './renderPaths'

export function PathsV2(): JSX.Element {
    const canvasRef = useRef<HTMLDivElement>(null)
    const canvasContainerRef = useRef<HTMLDivElement>(null)
    const { width: canvasWidth, height: canvasHeight } = useResizeObserver({ ref: canvasRef })
    const [nodes, setNodes] = useState<PathNodeData[]>([])

    const { insightProps } = useValues(insightLogic)
    const { insightQuery, paths, pathsFilter, funnelPathsFilter, insightDataLoading, insightDataError, theme } =
        useValues(pathsDataLogic(insightProps))
    const { openPersonsModal } = useActions(pathsDataLogic(insightProps))
    const { loadData } = useActions(insightDataLogic(insightProps))

    useEffect(() => {
        setNodes([])

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
            setNodes,
            openPersonsModal
        )

        // Proper cleanup
        return () => {
            const elements = canvasContainerRef.current?.querySelectorAll(`.Paths__canvas`)
            elements?.forEach((node) => node?.parentNode?.removeChild(node))
        }
    }, [paths, insightDataLoading, canvasWidth, canvasHeight, theme, pathsFilter, funnelPathsFilter, openPersonsModal])

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
        <div className="h-full w-full overflow-auto" ref={canvasContainerRef}>
            <div
                ref={canvasRef}
                className="Paths"
                data-attr="paths-viz"
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--paths-node': theme?.['preset-1'] || '#000000',
                        '--paths-node-hover': lightenDarkenColor(theme?.['preset-1'] || '#000000', -20),
                        '--paths-node-start-or-end': theme?.['preset-2'] || '#000000',
                        '--paths-node-start-or-end-hover': lightenDarkenColor(theme?.['preset-2'] || '#000000', -20),
                        '--paths-link': theme?.['preset-1'] || '#000000',
                        '--paths-link-hover': lightenDarkenColor(theme?.['preset-1'] || '#000000', -20),
                        '--paths-dropoff': 'rgba(220,53,69,0.7)',
                    } as React.CSSProperties
                }
            >
                {!insightDataLoading && paths && paths.nodes.length === 0 && !insightDataError && <InsightEmptyState />}
                {!insightDataError &&
                    nodes &&
                    nodes.map((node, idx) => <PathNodeLabel key={idx} node={node} insightProps={insightProps} />)}
            </div>
        </div>
    )
}
