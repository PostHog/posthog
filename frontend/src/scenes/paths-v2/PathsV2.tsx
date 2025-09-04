import './PathsV2.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { lightenDarkenColor } from 'lib/utils'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { shouldQueryBeAsync } from '~/queries/utils'

import { PathV2NodeLabel } from './PathV2NodeLabel'
import type { PathNodeData } from './pathUtils'
import { pathsV2DataLogic } from './pathsV2DataLogic'
import { renderPathsV2 } from './renderPathsV2'

export function PathsV2(): JSX.Element {
    const canvasRef = useRef<HTMLDivElement>(null)
    const canvasContainerRef = useRef<HTMLDivElement>(null)
    const { width: canvasWidth, height: canvasHeight } = useResizeObserver({ ref: canvasRef })
    const [nodes, setNodes] = useState<PathNodeData[]>([])

    const { insightProps } = useValues(insightLogic)
    const { insightQuery, paths, insightDataLoading, insightDataError, theme } = useValues(
        pathsV2DataLogic(insightProps)
    )
    const { loadData } = useActions(insightDataLogic(insightProps))

    useEffect(() => {
        setNodes([])

        // Remove the existing SVG canvas(es). The .PathsV2__canvas selector is crucial, as we have to be sure
        // we're only removing the Paths viz and not, for example, button icons.
        // Only remove canvases within this component's container
        const elements = canvasContainerRef.current?.querySelectorAll(`.PathsV2__canvas`)
        elements?.forEach((node) => node?.parentNode?.removeChild(node))

        renderPathsV2(canvasRef, canvasWidth, canvasHeight, paths, setNodes)

        // Proper cleanup
        return () => {
            const elements = canvasContainerRef.current?.querySelectorAll(`.PathsV2__canvas`)
            elements?.forEach((node) => node?.parentNode?.removeChild(node))
        }
    }, [paths, insightDataLoading, canvasWidth, canvasHeight, theme])

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
                className="PathsV2"
                data-attr="paths-viz"
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        // regular nodes
                        '--paths-node': theme?.['preset-1'] || '#000000',
                        '--paths-node--hover': lightenDarkenColor(theme?.['preset-1'] || '#000000', -20),

                        // aggregated "other" nodes
                        '--paths-node--other': theme?.['preset-2'] || '#000000',
                        '--paths-node--other-hover': lightenDarkenColor(theme?.['preset-2'] || '#000000', -20),

                        // dropoff nodes
                        '--paths-node--dropoff': 'var(--color-lifecycle-dormant)',
                        '--paths-node--dropoff-hover': 'var(--color-lifecycle-dormant-hover)',

                        '--paths-link': theme?.['preset-1'] || '#000000',
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
