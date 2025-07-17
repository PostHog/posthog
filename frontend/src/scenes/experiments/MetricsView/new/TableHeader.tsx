import { getNiceTickValues } from '../shared/utils'
import { NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { VIEW_BOX_WIDTH, SVG_EDGE_MARGIN, TICK_PANEL_HEIGHT, TICK_FONT_SIZE_NEW } from './constants'
import { useAxisScale } from './useAxisScale'
import { TickLabels } from './TickLabels'
import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { useEffect, useState, useMemo } from 'react'

interface TableHeaderProps {
    results: NewExperimentQueryResponse[]
    chartRadius?: number
}

export function TableHeader({ chartRadius }: TableHeaderProps): JSX.Element {
    const significanceHeader = 'Change'
    const [svgWidth, setSvgWidth] = useState<number | undefined>(undefined)

    // Set up tick values and scaling for the header
    const tickValues = useMemo(() => (chartRadius ? getNiceTickValues(chartRadius) : []), [chartRadius])
    const scale = useAxisScale(chartRadius || 0, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    const { ticksSvgRef } = useSvgResizeObserver([tickValues, chartRadius])

    // Track SVG width for font scaling compensation
    useEffect(() => {
        if (ticksSvgRef.current) {
            const updateWidth = (): void => {
                const rect = ticksSvgRef.current?.getBoundingClientRect()
                if (rect) {
                    setSvgWidth(rect.width)
                }
            }

            updateWidth()
            window.addEventListener('resize', updateWidth)
            return () => window.removeEventListener('resize', updateWidth)
        }
    }, [ticksSvgRef, tickValues, chartRadius])

    return (
        <thead>
            <tr>
                <th className="w-1/5 border-b-2 bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Metric
                </th>
                <th className="w-1/15 border-b-2 bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Variant
                </th>
                <th className="w-1/15 border-b-2 bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Value
                </th>
                <th className="w-1/15 border-b-2 bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    {significanceHeader}
                </th>
                <th className="min-w-[600px] border-b-2 bg-bg-table p-0 text-center text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    {chartRadius && chartRadius > 0 ? (
                        <div className="min-w-[600px]">
                            <svg
                                ref={ticksSvgRef}
                                viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT + 10}`}
                                preserveAspectRatio="xMidYMid meet"
                                className="w-full max-w-[1000px]"
                                style={{
                                    minHeight: `${TICK_PANEL_HEIGHT + 10}px`,
                                }}
                            >
                                <TickLabels
                                    tickValues={tickValues}
                                    scale={scale}
                                    y={TICK_PANEL_HEIGHT + 2}
                                    viewBoxWidth={VIEW_BOX_WIDTH}
                                    fontSize={TICK_FONT_SIZE_NEW}
                                    fontWeight="600"
                                    dominantBaseline="middle"
                                    svgWidth={svgWidth}
                                />
                            </svg>
                        </div>
                    ) : (
                        <div className="p-3">Chart</div>
                    )}
                </th>
                <th className="w-1/30 border-b-2 bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10" />
            </tr>
        </thead>
    )
}
