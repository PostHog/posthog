import React, { useState, useEffect /*useRef*/ } from 'react'
import * as d3 from 'd3'

// import { useActions, useValues } from 'kea'
import /*formatLabel, compactNumber,*/ '~/lib/utils'
// import { useWindowSize } from 'lib/hooks/useWindowSize'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'
// import dayjs from 'dayjs'
// import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
// import { InsightLabel } from 'lib/components/InsightLabel'
// import { FEATURE_FLAGS } from 'lib/constants'
// import { InsightTooltip } from '../InsightTooltip'
import { TrendResult } from '~/types'
import { PieArcDatum } from 'd3'

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
    dashboardItemId?: number
    inSharedMode?: boolean,
    percentage?: boolean,
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
            transform="translate(50,50)"
            onMouseOver={() => setHover(true)}
            onMouseOut={() => setHover(false)}
            style={{
                stroke,
                strokeWidth: hover ? hoverStrokeWidth : strokeWidth,
                strokeLinejoin: 'bevel',
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
    dashboardItemId,
    inSharedMode,
    percentage = false,
}:
PieChartProps): JSX.Element {
    const [focused, setFocused] = useState(false)
    const [arcs, setArcs] = useState<PieArc[]>([])
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

    return (
        <div
            className="graph-container"
            data-attr={dataAttr}
            // onMouseMove={() => setEnabled(true)}
            // onMouseLeave={() => setEnabled(false)}
        >
            <svg>
                {arcs
                    .map((arc) =>
                        d3.arc()({
                            ...arc,
                            innerRadius: 0,
                            outerRadius: 50,
                        })
                    ).map((d, index) => (
                        <ArcPath
                            d={d}
                            key={index}
                            backgroundColor={chartData.backgroundColor[index]}
                            borderColor={chartData.borderColor[index]}
                            borderWidth={chartData.borderWidth}
                            hoverBorderWidth={chartData.hoverBorderWidth}
                            transform="translate(50,50)"
                        />
                    ))}
            </svg>
            {/* <pre>
                inputDatasets: {JSON.stringify(inputDatasets)}
                labels: {JSON.stringify(labels)}
                dashboardItemId: {JSON.stringify(dashboardItemId)}
                inSharedMode: {JSON.stringify(inSharedMode)}
            </pre> */}
        </div>
    )
}
