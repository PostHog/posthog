import React, { useState, useEffect, useRef } from 'react'
import * as d3 from 'd3'
import /*formatLabel, compactNumber,*/ '~/lib/utils'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
import { TrendResult } from '~/types'
import { PieArcDatum } from 'd3'

import './PieChart.scss'

export type Dataset = TrendResult & {
    borderColor: string[]
    hoverBorderColor: string[]
    backgroundColor: string[]
    hoverBackgroundColor: string[]
    borderWidth: number
    hoverBorderWidth: number
}

type PieArc = PieArcDatum<number | { valueOf(): number }>

interface PieChartProps {
    datasets: Dataset[]
    labels: string[] //TODO
    color: string
    // type: any //TODO
    // onClick: CallableFunction
    ['data-attr']: string
}

const CHART_DEFAULTS = {
    borderColor: '#fff',
    hoverBorderColor: '#fff',
    backgroundColor: '#999',
    hoverBackgroundColor: '#999',
    borderWidth: 1,
    hoverBorderWidth: 1,
}

interface ArcPathProps {
    d: string | null
    backgroundColor?: string
    borderColor?: string
    borderWidth?: number
    hoverBorderWidth?: number
    transform: string
    onMouseOver: (e: React.MouseEvent) => any
    onMouseOut: (e: React.MouseEvent) => any
}

function ArcPath({
    d,
    backgroundColor,
    borderColor,
    borderWidth,
    hoverBorderWidth,
    transform,
    onMouseOver,
    onMouseOut,
}: ArcPathProps): JSX.Element | null {
    if (!d) {
        return null
    }
    const [hover, setHover] = useState(false)
    const strokeWidth = borderWidth ?? CHART_DEFAULTS.borderWidth
    const hoverStrokeWidth = hoverBorderWidth ?? CHART_DEFAULTS.hoverBorderWidth
    const stroke = borderColor ?? backgroundColor ?? CHART_DEFAULTS.borderColor

    return (
        <path
            d={d}
            fill={backgroundColor || CHART_DEFAULTS.backgroundColor}
            transform={transform}
            onMouseOver={(e) => {
                setHover(true)
                onMouseOver(e)
            }}
            onMouseOut={function (e) {
                setHover(false)
                onMouseOut(e)
            }}
            style={{
                stroke,
                strokeWidth: hover ? hoverStrokeWidth : strokeWidth,
                strokeLinejoin: 'bevel',
                transform: 'all 0.2s ease',
            }}
        />
    )
}

function SVGTooltip({ x, y, label }: { x: number; y: number; label: string }): JSX.Element {
    // TODO: use foreignElement to inject custom tooltip
    return (
        <text textAnchor="middle" x={x} y={y} onMouseOver={(e) => e.stopPropagation()}>
            {label}
        </text>
    )
}

// const noop = () => {}
export function PieChart({
    datasets: inputDatasets,
    labels,
    color,
    // type,
    // onClick,
    ['data-attr']: dataAttr,
}: PieChartProps): JSX.Element {
    const [focused, setFocused] = useState(false)
    const [arcs, setArcs] = useState<PieArc[]>([])
    const [hoverIndex, setHoverIndex] = useState<number | null>(null)
    const [tooltipPosition, setTooltipPosition] = useState<number[] | null>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const chartData = inputDatasets[0] // Eventually, we'll support multiple pie series

    useEscapeKey(() => setFocused(false), [focused])

    useEffect(() => {
        buildChart()
    }, [chartData, color])

    function buildChart(): void {
        const _arcs = d3.pie()(chartData.data)
        setArcs(_arcs)
    }

    // TODO: Try using https://developer.mozilla.org/en-US/docs/Web/API/ResizeObserver/observe
    const viewBoxWidth = containerRef.current?.clientWidth || 800
    const viewBoxHeight = containerRef.current?.clientHeight || 400
    const innerRadius = 0,
        outerRadius = viewBoxHeight * 0.45
    const center = [viewBoxWidth / 2, viewBoxHeight / 2]
    return (
        <div className="graph-container" data-attr={dataAttr} ref={containerRef}>
            <svg viewBox={`0 0 ${viewBoxWidth} ${viewBoxHeight}`} style={{ width: '100%', height: '100%' }}>
                {arcs.map((arc, index) => {
                    const arcObject = {
                        ...arc,
                        innerRadius,
                        outerRadius,
                    }
                    const centroidOffset = d3.arc().centroid(arcObject)
                    const centroid = [center[0] + centroidOffset[0], center[1] + centroidOffset[1]]
                    return (
                        <>
                            <ArcPath
                                d={d3.arc()(arcObject)}
                                key={index}
                                backgroundColor={chartData.backgroundColor[index]}
                                borderColor={chartData.borderColor[index]}
                                borderWidth={chartData.borderWidth}
                                hoverBorderWidth={chartData.hoverBorderWidth}
                                transform={`translate(${center.join(',')})`}
                                onMouseOver={() => {
                                    setHoverIndex(index)
                                    setTooltipPosition(centroid)
                                }}
                                onMouseOut={() => {
                                    setHoverIndex(null)
                                    setTooltipPosition(null)
                                }}
                            />
                        </>
                    )
                })}
                {hoverIndex !== null && tooltipPosition && (
                    <SVGTooltip x={tooltipPosition[0]} y={tooltipPosition[1]} label={labels[hoverIndex]} />
                )}
            </svg>
        </div>
    )
}
