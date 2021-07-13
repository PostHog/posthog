import React from 'react'
import * as d3 from 'd3'
import { D3Selector, useD3 } from 'lib/hooks/useD3'
import { FunnelLayout } from 'lib/constants'
import { getChartColors } from 'lib/colors'

import './Histogram.scss'

interface HistogramDatum {
    id: string | number
    bin0: number
    bin1: number
    count: number
}

interface HistogramProps {
    data: HistogramDatum[]
    layout?: FunnelLayout
    xLabel?: string
    yLabel?: string
    color?: string
}

interface HistogramConfig {
    height: number
    width: number
    margin: { top: number; right: number; bottom: number; left: number }
    spacer: number
    ranges: { x: number[]; y: number[] }
    transforms: { x: string; y: string }
    axisFn: { x: any; y: any }
}

const INITIAL_CONFIG = {
    height: 500,
    width: 500,
    margin: { top: 20, right: 20, bottom: 30, left: 40 },
    spacer: 6,
}

const getConfig = (isVertical: boolean): HistogramConfig => ({
    ...INITIAL_CONFIG,
    ranges: {
        x: isVertical
            ? [INITIAL_CONFIG.margin.left, INITIAL_CONFIG.width - INITIAL_CONFIG.margin.right]
            : [INITIAL_CONFIG.height - INITIAL_CONFIG.margin.bottom, INITIAL_CONFIG.margin.top],
        y: isVertical
            ? [INITIAL_CONFIG.height - INITIAL_CONFIG.margin.bottom, INITIAL_CONFIG.margin.top]
            : [INITIAL_CONFIG.margin.left, INITIAL_CONFIG.width - INITIAL_CONFIG.margin.right],
    },
    transforms: {
        x: isVertical
            ? `translate(0,${INITIAL_CONFIG.height - INITIAL_CONFIG.margin.bottom})`
            : `translate(${INITIAL_CONFIG.margin.left},0)`,
        y: isVertical
            ? `translate(${INITIAL_CONFIG.margin.left},0)`
            : `translate(0,${INITIAL_CONFIG.height - INITIAL_CONFIG.margin.bottom})`,
    },
    axisFn: {
        x: isVertical ? d3.axisBottom : d3.axisLeft,
        y: isVertical ? d3.axisLeft : d3.axisBottom,
    },
})

export function Histogram({
    data,
    layout = FunnelLayout.vertical,
    // xLabel = "",
    // yLabel = "",
    color = 'white',
}: HistogramProps): JSX.Element {
    const colorList = getChartColors(color)

    // Initial dimensions
    const isVertical = layout === FunnelLayout.vertical
    const config = getConfig(isVertical)

    const ref = useD3(
        (container) => {
            const xMax = data[data.length - 1].bin1
            const x = d3.scaleLinear().domain([data[0].bin0, xMax]).range(config.ranges.x)

            const xAxis = config.axisFn.x(x).tickValues([...data.map((d) => d.bin0), xMax])
            // .text(data.x))

            const y = d3
                .scaleLinear()
                .domain([0, d3.max(data, (d: HistogramDatum) => d.count)])
                .nice()
                .range(config.ranges.y)

            const yAxis = config.axisFn.y(y)
            // .text(data.y))

            const renderCanvas = (parentNode: D3Selector): D3Selector => {
                // Get or create svg > g
                let _svg = parentNode.select('svg > g')
                if (_svg.empty()) {
                    _svg = parentNode
                        .append('svg:svg')
                        .attr('viewBox', [0, 0, config.width, config.height])
                        .append('svg:g')
                }

                const accessors = {
                    x: (d: HistogramDatum) => (isVertical ? x(d.bin0) + INITIAL_CONFIG.spacer / 2 : x(0)),
                    y: (d: HistogramDatum) => (isVertical ? y(d.count) : x(d.bin0) + INITIAL_CONFIG.spacer / 2),
                    width: (d: HistogramDatum) =>
                        isVertical ? Math.max(0, x(d.bin1) - x(d.bin0) - INITIAL_CONFIG.spacer) : y(0) - y(d.count),
                    height: (d: HistogramDatum) =>
                        isVertical ? y(0) - y(d.count) : Math.max(0, x(d.bin1) - x(d.bin0) - INITIAL_CONFIG.spacer),
                }

                _svg.attr('fill', colorList[0])
                    .selectAll('rect')
                    .data(data)
                    .join('rect')
                    .transition()
                    .duration(1000)
                    .attr('x', accessors.x)
                    .attr('width', accessors.width)
                    .attr('y', accessors.y)
                    .attr('height', accessors.height)

                // Get or create x axis
                let _xAxis = _svg.select('g#x-axis')
                if (_xAxis.empty()) {
                    _xAxis = _svg.append('g').attr('id', 'x-axis').attr('transform', config.transforms.x)
                }
                _xAxis.transition().duration(1000).call(xAxis)

                // Get or create y axis
                let _yAxis = _svg.select('g#y-axis')
                if (_yAxis.empty()) {
                    _yAxis = _svg.append('g').attr('id', 'y-axis').attr('transform', config.transforms.y)
                }
                _yAxis.transition().duration(1000).call(yAxis)

                return _svg
            }

            renderCanvas(container)
        },
        [data, layout]
    )

    return <div className="histogram-container" ref={ref} />
}
