import React, { useEffect } from 'react'
import * as d3 from 'd3'
import { D3Selector, D3Transition, useD3 } from 'lib/hooks/useD3'
import { FunnelLayout } from 'lib/constants'
import { createRoundedRectPath, getConfig, INITIAL_CONFIG } from './histogramUtils'
import { getOrCreateEl, animate, wrap } from 'lib/utils/d3Utils'

import './Histogram.scss'
import { useActions, useValues } from 'kea'
import { histogramLogic } from 'scenes/insights/Histogram/histogramLogic'

export interface HistogramDatum {
    id: string | number
    bin0: number
    bin1: number
    count: number
}

interface HistogramProps {
    data: HistogramDatum[]
    layout?: FunnelLayout
    isAnimated?: boolean
    width?: number
    height?: number
    formatXTickLabel?: (value: number) => number | string
}

export function Histogram({
    data,
    layout = FunnelLayout.vertical,
    width = INITIAL_CONFIG.width,
    height = INITIAL_CONFIG.height,
    isAnimated = false,
    formatXTickLabel = (value: number) => value,
}: HistogramProps): JSX.Element {
    const { config } = useValues(histogramLogic)
    const { setConfig } = useActions(histogramLogic)
    const isEmpty = data.length === 0 || d3.sum(data.map((d) => d.count)) === 0

    // TODO: All D3 state outside of useD3 hook will be moved into separate kea histogramLogic

    // Initialize x-axis and y-axis scales
    const xMin = data?.[0]?.bin0 || 0
    const xMax = data?.[data.length - 1]?.bin1 || 1
    const xSecond = data?.[0]?.bin1 || xMax
    const x = d3.scaleLinear().domain([xMin, xMax]).range(config.ranges.x).nice()
    const xAxis = config.axisFn
        .x(x)
        .tickValues([...data.map((d) => d.bin0), xMax])
        // v === -2 || v === -1 represent bins that catch grouped outliers.
        // TODO: (-2, -1) are temporary placeholders for (-inf, +inf) and should be changed when backend specs are finalized
        .tickFormat((v: number) => {
            const label = formatXTickLabel(v)
            if (v === -2) {
                return `<${label}`
            }
            if (v === -1) {
                return `>=${label}`
            }
            return label
        })

    // y-axis scale
    const y = d3
        .scaleLinear()
        .domain([0, d3.max(data, (d: HistogramDatum) => d.count) as number])
        .range(config.ranges.y)
        .nice()
    const yAxis = config.axisFn.y(y).tickSize(0)

    // y-axis gridline scale
    const yAxisGrid = config.axisFn.y(y).tickSize(-config.gridlineTickSize).tickFormat('').ticks(y.ticks().length)

    // Update config to new values if dimensions change
    useEffect(() => {
        setConfig(getConfig(layout, width, height))
    }, [layout, width, height])

    const ref = useD3(
        (container) => {
            const renderCanvas = (parentNode: D3Selector): D3Selector => {
                // Update config to reflect dimension changes
                x.range(config.ranges.x)
                y.range(config.ranges.y)
                yAxisGrid.tickSize(-config.gridlineTickSize)

                // Get or create svg > g
                const _svg = getOrCreateEl(parentNode, 'svg > g', () =>
                    parentNode
                        .append('svg:svg')
                        .attr('viewBox', `0 0 ${config.inner.width} ${config.inner.height}`)
                        .attr('width', '100%')
                        .append('svg:g')
                        .classed(layout, true)
                )
                // update dimensions
                parentNode.select('svg').attr('viewBox', `0 0 ${config.width} ${config.height}`)

                // if class doesn't exist on svg>g, layout has changed. after we learn this, reset
                // the layout
                const layoutChanged = !_svg.classed(layout)
                _svg.attr('class', null).classed(layout, true)

                // if layout changes, redraw axes from scratch
                if (layoutChanged) {
                    _svg.selectAll('#x-axis,#y-axis,#y-gridlines').remove()
                }

                // x-axis
                const _xAxis = getOrCreateEl(_svg, 'g#x-axis', () =>
                    _svg.append('svg:g').attr('id', 'x-axis').attr('transform', config.transforms.x)
                )
                _xAxis.call(animate, !layoutChanged ? config.transitionDuration : 0, isAnimated, (it: D3Transition) =>
                    it.call(xAxis).attr('transform', config.transforms.x)
                )
                _xAxis.selectAll('.tick text').call(wrap, x(xSecond) - x(0), config.spacing.labelLineHeight)

                // Don't draw y-axis or y-gridline if the data is empty
                if (!isEmpty) {
                    // y-axis
                    const _yAxis = getOrCreateEl(_svg, 'g#y-axis', () =>
                        _svg.append('svg:g').attr('id', 'y-axis').attr('transform', config.transforms.y)
                    )
                    _yAxis.call(
                        animate,
                        !layoutChanged ? config.transitionDuration : 0,
                        isAnimated,
                        (it: D3Transition) =>
                            it
                                .call(yAxis)
                                .attr('transform', config.transforms.y)
                                .call((g) => g.selectAll('.tick text').attr('dy', `-${config.spacing.yLabel}`))
                    )

                    // y-gridlines
                    const _yGridlines = getOrCreateEl(_svg, 'g#y-gridlines', () =>
                        _svg.append('svg:g').attr('id', 'y-gridlines').attr('transform', config.transforms.yGrid)
                    )
                    _yGridlines.call(
                        animate,
                        !layoutChanged ? config.transitionDuration : 0,
                        isAnimated,
                        (it: D3Transition) =>
                            it
                                .call(yAxisGrid)
                                .call((g) =>
                                    g
                                        .selectAll('.tick:not(:first-of-type) line')
                                        .attr('stroke-opacity', 0.5)
                                        .attr('stroke-dasharray', '2,2')
                                )
                                .attr('transform', config.transforms.yGrid)
                    )
                }

                // bars
                const _bars = getOrCreateEl(_svg, 'g#bars', () => _svg.append('svg:g').attr('id', 'bars'))
                _bars
                    .selectAll('path')
                    .data(data)
                    .join('path')
                    .call(animate, config.transitionDuration, isAnimated, (it: D3Transition) => {
                        return it.attr('d', (d: HistogramDatum) => {
                            if (layout === FunnelLayout.vertical) {
                                return createRoundedRectPath(
                                    x(d.bin0) + config.spacing.btwnBins / 2,
                                    y(d.count),
                                    Math.max(0, x(d.bin1) - x(d.bin0) - config.spacing.btwnBins),
                                    y(0) - y(d.count),
                                    config.borderRadius,
                                    'top'
                                )
                            }
                            // is horizontal
                            return createRoundedRectPath(
                                y(0),
                                x(d.bin0) + config.spacing.btwnBins / 2,
                                y(d.count) - y(0),
                                Math.max(0, x(d.bin1) - x(d.bin0) - config.spacing.btwnBins),
                                config.borderRadius,
                                'right'
                            )
                        })
                    })

                return _svg
            }

            renderCanvas(container)
        },
        [data, layout, config]
    )

    return <div className="histogram-container" ref={ref} />
}
