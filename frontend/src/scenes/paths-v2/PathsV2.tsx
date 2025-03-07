import './Paths.scss'

import { useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { lightenDarkenColor } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelPathsFilter } from '~/queries/schema/schema-general'

import { PathV2NodeLabel } from './PathNodeLabel'
import { pathsV2DataLogic } from './pathsV2DataLogic'
import type { PathNodeData } from './pathUtils'
import { renderPathsV2 } from './renderPathsV2'

export function PathsV2(): JSX.Element {
    const canvasRef = useRef<HTMLDivElement>(null)
    const canvasContainerRef = useRef<HTMLDivElement>(null)
    const { width: canvasWidth, height: canvasHeight } = useResizeObserver({ ref: canvasRef })
    const [nodes, setNodes] = useState<PathNodeData[]>([])

    const { insightProps } = useValues(insightLogic)
    const { insightQuery, paths, pathsFilter, insightDataLoading, insightDataError, theme } = useValues(
        pathsV2DataLogic(insightProps)
    )

    useEffect(() => {
        setNodes([])

        // Remove the existing SVG canvas(es). The .Paths__canvas selector is crucial, as we have to be sure
        // we're only removing the Paths viz and not, for example, button icons.
        // Only remove canvases within this component's container
        const elements = canvasContainerRef.current?.querySelectorAll(`.Paths__canvas`)
        elements?.forEach((node) => node?.parentNode?.removeChild(node))

        renderPathsV2(canvasRef, canvasWidth, canvasHeight, paths, pathsFilter || {}, setNodes)

        // Proper cleanup
        return () => {
            const elements = canvasContainerRef.current?.querySelectorAll(`.Paths__canvas`)
            elements?.forEach((node) => node?.parentNode?.removeChild(node))
        }
    }, [paths, insightDataLoading, canvasWidth, canvasHeight, theme, pathsFilter])

    if (insightDataError) {
        return <InsightErrorState query={insightQuery} excludeDetail />
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
                        // regular nodes
                        '--paths-node': theme?.['preset-1'] || '#000000',
                        '--paths-node--hover': lightenDarkenColor(theme?.['preset-1'] || '#000000', -20),

                        // aggregated "other" nodes
                        '--paths-node--other': theme?.['preset-2'] || '#000000',

                        // dropoff nodes
                        '--paths-node--dropoff': 'rgba(220, 53, 69, 0.7)', //theme?.['preset-1'] || '#000000',

                        '--paths-node--start-or-end': theme?.['preset-2'] || '#000000',
                        '--paths-node--start-or-end-hover': lightenDarkenColor(theme?.['preset-2'] || '#000000', -20),
                        '--paths-link': theme?.['preset-1'] || '#000000',
                        // '--paths-link--hover': lightenDarkenColor(theme?.['preset-1'] || '#000000', -20),

                        // '--paths-dropoff': 'rgba(220,53,69,0.7)',
                    } as React.CSSProperties
                }
            >
                {!insightDataLoading && paths && paths.nodes.length === 0 && !insightDataError && <InsightEmptyState />}
                {!insightDataError &&
                    nodes &&
                    nodes.map((node, idx) => <PathV2NodeLabel key={idx} node={node} insightProps={insightProps} />)}
            </div>
        </div>
    )
}
