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
}

function ArcPath({ d, backgroundColor, borderColor, borderWidth, hoverBorderWidth, transform }: ArcPathProps): JSX.Element | null {
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
            onMouseOver={() => setHover(true)}
            onMouseOut={() => setHover(false)}
            style={{
                stroke,
                strokeWidth: hover ? hoverStrokeWidth : strokeWidth,
                strokeLinejoin: 'bevel',
                transform: 'all 0.2s ease',
            }}
        />
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
}:
PieChartProps): JSX.Element {
    const [focused, setFocused] = useState(false)
    const [arcs, setArcs] = useState<PieArc[]>([])
    const containerRef = useRef<HTMLDivElement>(null)
    const chartData = inputDatasets[0] // Eventually, we'll support multiple pie series

    useEscapeKey(() => setFocused(false), [focused])

    useEffect(() => {
        buildChart()
    }, [chartData, color])

    function buildChart(): void {
        const _arcs = d3.pie()(chartData.data)
        console.log('arcs:', _arcs)
        setArcs(_arcs)
    }

    const viewBoxWidth = containerRef.current?.clientWidth || 800
    const viewBoxHeight = containerRef.current?.clientHeight || 400
    const innerRadius = 0, outerRadius = viewBoxHeight * 0.45
    const center = { x: viewBoxWidth / 2, y: viewBoxHeight / 2 }
    return (
        <div
            className="graph-container"
            data-attr={dataAttr}
            ref={containerRef}
        >
            <svg viewBox={`0 0 ${viewBoxWidth} ${viewBoxHeight}`}>
                {arcs
                    .map((arc, index) => (
                        <ArcPath
                            d={d3.arc()({
                                ...arc,
                                innerRadius,
                                outerRadius,
                            })}
                            key={index}
                            backgroundColor={chartData.backgroundColor[index]}
                            borderColor={chartData.borderColor[index]}
                            borderWidth={chartData.borderWidth}
                            hoverBorderWidth={chartData.hoverBorderWidth}
                            transform={`translate(${center.x},${center.y})`}
                        />
                    ))
                }
            </svg>
        </div>
    )
}
