import './PathsV2.scss'

import { useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { lightenDarkenColor } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'

import { PathV2NodeLabel } from './PathV2NodeLabel'
import { pathsV2DataLogic } from './pathsV2DataLogic'
import type { PathNodeData } from './pathUtils'
import { renderPathsV2 } from './renderPathsV2'

function DebugPathTable(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightData } = useValues(pathsV2DataLogic(insightProps))

    if (!insightData?.result) {
        return null
    }

    return (
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800">
                <tr>
                    {Object.keys(insightData.result[0] || {}).map((key) => (
                        <th
                            key={key}
                            scope="col"
                            className="px-2 py-1 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
                        >
                            {key}
                        </th>
                    ))}
                </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                {insightData.result.map((item, index) => (
                    <tr key={index}>
                        {Object.values(item).map((value, idx) => (
                            <td
                                key={idx}
                                className="px-2 py-1 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300"
                            >
                                {JSON.stringify(value)}
                            </td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    )
}

export function PathsV2(): JSX.Element {
    const canvasRef = useRef<HTMLDivElement>(null)
    const canvasContainerRef = useRef<HTMLDivElement>(null)
    const { width: canvasWidth, height: canvasHeight } = useResizeObserver({ ref: canvasRef })
    const [nodes, setNodes] = useState<PathNodeData[]>([])

    const { insightProps } = useValues(insightLogic)
    const { insightQuery, paths, insightDataLoading, insightDataError, theme } = useValues(
        pathsV2DataLogic(insightProps)
    )

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
        return <InsightErrorState query={insightQuery} excludeDetail />
    }

    return (
        <>
            <DebugPathTable />
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
                            '--paths-node--dropoff': '#db3707',
                            '--paths-node--dropoff-hover': lightenDarkenColor('#db3707', -20),

                            '--paths-link': theme?.['preset-1'] || '#000000',
                        } as React.CSSProperties
                    }
                >
                    {!insightDataLoading && paths && paths.nodes.length === 0 && !insightDataError && (
                        <InsightEmptyState />
                    )}
                    {!insightDataError &&
                        nodes &&
                        nodes.map((node, idx) => <PathV2NodeLabel key={idx} node={node} insightProps={insightProps} />)}
                </div>
            </div>
        </>
    )
}
