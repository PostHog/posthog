import './Histogram.scss'

import * as d3 from 'd3'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FunnelLayout } from 'lib/constants'
import { D3Selector, D3Transition, useD3 } from 'lib/hooks/useD3'
import { animate, getOrCreateEl, wrap } from 'lib/utils/d3Utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { histogramLogic } from 'scenes/insights/views/Histogram/histogramLogic'

import { D3HistogramDatum, INITIAL_CONFIG, createRoundedRectPath, getConfig } from './histogramUtils'

export interface HistogramDatum {
    id: string | number
    bin0: number
    bin1: number
    count: number
    label: string | number
}

interface HistogramProps {
    data: HistogramDatum[]
    layout?: FunnelLayout
    isAnimated?: boolean
    isDashboardItem?: boolean
    width?: number
    height?: number
    formatXTickLabel?: (value: number) => number | string
    formatYTickLabel?: (value: number) => number
}

export function Histogram({
    data,
    layout = FunnelLayout.vertical,
    width = INITIAL_CONFIG.width,
    height = INITIAL_CONFIG.height,
    isAnimated = false,
    isDashboardItem = false,
    formatXTickLabel = (value: number) => value,
    formatYTickLabel = (value: number) => value,
}: HistogramProps): JSX.Element {
    const { config } = useValues(histogramLogic)
    const { setConfig } = useActions(histogramLogic)
    const { insightProps } = useValues(insightLogic)
    const { theme } = useValues(insightVizDataLogic(insightProps))

    const backgroundColor = theme?.['preset-1'] || '#000000' // Default to black if no color found

    const isEmpty = data.length === 0 || d3.sum(data.map((d) => d.count)) === 0

    // Initialize x-axis and y-axis scales
    const xMin = data?.[0]?.bin0 || 0
    const xMax = data?.[data.length - 1]?.bin1 || 1
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
    const yMax = d3.max(data, (d: HistogramDatum) => d.count) as number
    const y = d3.scaleLinear().domain([0, yMax]).range(config.ranges.y).nice()
    const yAxis = config.axisFn
        .y(y)
        .tickValues(y.ticks().filter((tick) => Number.isInteger(tick)))
        .tickSize(0)
        .tickFormat((v: number) => {
            const count = formatYTickLabel(v)
            // SI-prefix with trailing zeroes trimmed off
            return d3.format('~s')(count)
        })

    // y-axis gridline scale
    const yAxisGrid = config.axisFn.y(y).tickSize(-config.gridlineTickSize).tickFormat('').ticks(y.ticks().length)

    // Update config to new values if dimensions change
    useEffect(() => {
        const minWidth = Math.max(
            width,
            data.length * (config.spacing.minBarWidth + config.spacing.btwnBins) +
                config.margin.left +
                config.margin.right
        )
        setConfig(getConfig(layout, isDashboardItem ? width : minWidth, height))
    }, [data.length, layout, width, height]) // oxlint-disable-line react-hooks/exhaustive-deps

    const ref = useD3(
        (container) => {
            const isVertical = config.layout === FunnelLayout.vertical

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
                        .classed(config.layout, true)
                )
                // update dimensions
                parentNode.select('svg').attr('viewBox', `0 0 ${config.width} ${config.height}`)

                // if class doesn't exist on svg>g, layout has changed. after we learn this, reset
                // the layout
                const layoutChanged = !_svg.classed(config.layout)
                _svg.attr('class', null).classed(config.layout, true)

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
                const binWidth = x(data?.[0]?.bin1 || data?.[data.length - 1]?.bin1 || 1) - x(data?.[0]?.bin0 || 0)
                _xAxis
                    .selectAll('.tick text')
                    .call(
                        wrap,
                        isVertical ? binWidth : config.margin.left,
                        config.spacing.labelLineHeight,
                        isVertical,
                        config.spacing.xLabel
                    )

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
                                .call((g) =>
                                    g.selectAll('.tick text').attr('dx', isVertical ? `-${config.spacing.yLabel}` : 0)
                                )
                    )

                    // y-gridlines
                    const _yGridlines = getOrCreateEl(_svg, 'g#y-gridlines', () =>
                        _svg.append('svg:g').attr('id', 'y-gridlines').attr('transform', config.transforms.yGrid)
                    )
                    _yGridlines.call(
                        animate,
                        !layoutChanged ? config.transitionDuration : 0,
                        isAnimated,
                        (it: D3Transition) => it.call(yAxisGrid).attr('transform', config.transforms.yGrid)
                    )
                }

                const d3Data = data as D3HistogramDatum[]

                // bars
                const _bars = getOrCreateEl(_svg, 'g#bars', () => _svg.append('svg:g').attr('id', 'bars'))
                _bars
                    .selectAll('path')
                    .data(d3Data)
                    .join('path')
                    .call(animate, config.transitionDuration, isAnimated, (it: D3Transition) => {
                        return it.attr('d', (d: HistogramDatum) => {
                            if (!isVertical) {
                                // is horizontal
                                return createRoundedRectPath(
                                    y(0),
                                    x(d.bin0) + config.spacing.btwnBins / 2,
                                    y(d.count) - y(0),
                                    Math.max(0, x(d.bin1) - x(d.bin0) - config.spacing.btwnBins),
                                    config.borderRadius,
                                    'right'
                                )
                            }
                            return createRoundedRectPath(
                                x(d.bin0) + config.spacing.btwnBins / 2,
                                y(d.count),
                                Math.max(0, x(d.bin1) - x(d.bin0) - config.spacing.btwnBins),
                                y(0) - y(d.count),
                                config.borderRadius,
                                'top'
                            )
                        })
                    })

                // Always move bar above everything else
                _svg.node().appendChild(_bars.node())

                // text labels
                const _labels = getOrCreateEl(_svg, 'g#labels', () => _svg.append('svg:g').attr('id', 'labels'))
                _labels
                    .selectAll('text')
                    .data(d3Data)
                    .join('text')
                    .text((d) => d.label)
                    .classed('bar-label', true)
                    .each(function (this: any, d) {
                        const { width: labelWidth, height: labelHeight } = this.getBBox()
                        d.labelWidth = labelWidth
                        d.labelHeight = labelHeight
                        d.shouldShowInBar = false
                    })
                    .attr('x', (d) => {
                        if (!isVertical) {
                            const labelWidth = (d.labelWidth || 0) + 2 * config.spacing.barLabelPadding
                            const shouldShowInBar = labelWidth <= y(d.count) - y(0)
                            const labelDx = shouldShowInBar
                                ? -(labelWidth - config.spacing.barLabelPadding)
                                : config.spacing.barLabelPadding
                            d.shouldShowInBar = shouldShowInBar
                            return y(d.count) + labelDx
                        }
                        // x + bin width + dx + dy
                        return x(d.bin0) + binWidth / 2 - (d.labelWidth || 0) / 2
                    })
                    .attr('y', (d) => {
                        if (!isVertical) {
                            return x(d.bin0) + binWidth / 2
                        }
                        // determine if label should be in the bar or above it.
                        const labelHeight = (d.labelHeight || 0) + 2 * config.spacing.barLabelPadding
                        const shouldShowInBar = labelHeight <= y(0) - y(d.count)
                        const labelDy = shouldShowInBar
                            ? labelHeight - config.spacing.barLabelPadding
                            : -config.spacing.barLabelPadding
                        d.shouldShowInBar = shouldShowInBar
                        return y(d.count) + labelDy
                    })
                    .classed('outside', (d) => !d.shouldShowInBar)

                // Always move labels to top
                _svg.node().appendChild(_labels.node())

                return _svg
            }

            renderCanvas(container)
        },
        [data, config]
    )

    /* minWidth required to enforce d3's width calculations on the div wrapping the svg
     so that scrolling horizontally works */

    return (
        <div
            className="histogram-container"
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ minWidth: config.width, '--histogram-fill': backgroundColor } as React.CSSProperties}
        />
    )
}
