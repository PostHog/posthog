import { useEffect, useMemo, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'

import { ExperimentStatsMethod } from '~/types'

import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { getNiceTickValues } from '../shared/utils'
import { SVG_EDGE_MARGIN, TICK_FONT_SIZE_NEW, TICK_PANEL_HEIGHT, VIEW_BOX_WIDTH } from './constants'
import { TickLabels } from './TickLabels'
import { useAxisScale } from './useAxisScale'

interface TableHeaderProps {
    axisRange?: number
    statsMethod?: ExperimentStatsMethod
    sequentialTestingEnabled?: boolean
    loading?: boolean
}

export function TableHeader({
    axisRange,
    statsMethod,
    sequentialTestingEnabled,
    loading = false,
}: TableHeaderProps): JSX.Element {
    const [svgWidth, setSvgWidth] = useState<number | undefined>(undefined)

    // Set up tick values and scaling for the header
    const tickValues = useMemo(() => (axisRange ? getNiceTickValues(axisRange) : []), [axisRange])
    const scale = useAxisScale(axisRange || 0, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    const { ticksSvgRef } = useSvgResizeObserver([tickValues, axisRange])

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
    }, [ticksSvgRef, tickValues, axisRange])

    return (
        <thead>
            <tr>
                <th className="w-1/5 border-b-2 bg-bg-table p-3 text-left text-xs sticky top-0 z-10 metric-cell-header">
                    Metric
                </th>
                <th className="w-1/15 border-b-2 bg-bg-table p-3 text-left text-xs sticky top-0 z-10 metric-cell-header">
                    Variant
                </th>
                <th className="w-1/15 border-b-2 bg-bg-table p-3 text-left text-xs sticky top-0 z-10 metric-cell-header">
                    Value
                </th>
                <th className="w-1/15 border-b-2 bg-bg-table p-3 text-left text-xs sticky top-0 z-10 metric-cell-header">
                    Delta
                </th>
                <th className="w-1/15 border-b-2 bg-bg-table p-3 text-center text-xs sticky top-0 z-10 metric-cell-header whitespace-nowrap">
                    {statsMethod === ExperimentStatsMethod.Frequentist ? (
                        sequentialTestingEnabled ? (
                            <span className="inline-flex items-center gap-1">
                                P-value
                                <Tooltip title="Sequential testing is enabled. These are always-valid p-values, robust to peeking. They have a slightly different interpretation than ordinary p-values and can often be exactly 1.000 early in the experiment. The result is still statistically significant if the p-value drops below your threshold.">
                                    <IconInfo className="text-secondary text-base" />
                                </Tooltip>
                            </span>
                        ) : (
                            'P-value'
                        )
                    ) : (
                        <span className="inline-flex items-center gap-1">
                            Win %
                            <Tooltip title="Probability of outperforming control, not a percentage lift.">
                                <IconInfo className="text-secondary text-base" />
                            </Tooltip>
                        </span>
                    )}
                </th>
                <th className="border-b-2 bg-bg-table p-3 z-10" />
                <th className="border-b-2 bg-bg-table p-0 z-10">
                    {axisRange && axisRange > 0 ? (
                        <div>
                            <svg
                                ref={ticksSvgRef}
                                viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT + 10}`}
                                preserveAspectRatio="xMidYMid meet"
                                className="w-full"
                                style={{
                                    minHeight: `${TICK_PANEL_HEIGHT + 10}px`,
                                }}
                            >
                                <TickLabels
                                    tickValues={tickValues}
                                    scale={scale}
                                    y={(TICK_PANEL_HEIGHT + 13) / 2}
                                    viewBoxWidth={VIEW_BOX_WIDTH}
                                    fontSize={TICK_FONT_SIZE_NEW}
                                    fontWeight="600"
                                    dominantBaseline="middle"
                                    svgWidth={svgWidth}
                                />
                            </svg>
                        </div>
                    ) : (
                        <div className="p-3" />
                    )}
                </th>
            </tr>
            {/* Thin loader line spanning the full table width, pinned to the header's bottom edge.
                Mirrors LemonTable's loader row: a zero-height positioning host for the absolute line. */}
            <tr>
                <th colSpan={7} className="relative h-0 overflow-visible !border-none !p-0 leading-none">
                    <LemonTableLoader loading={loading} tag="div" placement="bottom" />
                </th>
            </tr>
        </thead>
    )
}
