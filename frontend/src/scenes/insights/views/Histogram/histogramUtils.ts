import * as d3 from 'd3'

import { FunnelLayout } from 'lib/constants'
import { HistogramDatum } from 'scenes/insights/views/Histogram/Histogram'

export interface HistogramConfig {
    layout: FunnelLayout
    height: number
    width: number
    inner: { height: number; width: number }
    margin: { top: number; right: number; bottom: number; left: number }
    borderRadius: number
    ranges: { x: number[]; y: number[] }
    gridlineTickSize: number
    transforms: { x: string; y: string; yGrid: string }
    axisFn: { x: any; y: any }
    transitionDuration: number
    spacing: {
        btwnBins: number
        yLabel: number
        xLabel: number
        labelLineHeight: number
        barLabelPadding: number
        minBarWidth: number
    }
}

export const INITIAL_CONFIG = {
    layout: FunnelLayout.vertical,
    height: 352,
    width: 500,
    margin: { top: 20, right: 20, bottom: 20, left: 40 },
    borderRadius: 4, // same as funnel bar graph,
    transitionDuration: 200, // in ms; same as in funnel bar graph
    spacing: {
        btwnBins: 6, // spacing between bins
        yLabel: 5, // y-axis label xOffset in vertical position
        xLabel: 8, // x-axis label xOffset in horizontal position
        labelLineHeight: 1.2, // line height of wrapped label text in em's,
        barLabelPadding: 8, // padding between bar and bar label,
        minBarWidth: 90, // minimum bar width
    },
}

export const getConfig = (layout: FunnelLayout, width?: number, height?: number): HistogramConfig => {
    const _width = width || INITIAL_CONFIG.width,
        _height = height || INITIAL_CONFIG.height
    const isVertical = layout === FunnelLayout.vertical

    return {
        ...INITIAL_CONFIG,
        layout,
        height: _height,
        width: _width,
        inner: {
            height: _height - INITIAL_CONFIG.margin.bottom - INITIAL_CONFIG.margin.top,
            width: _width - INITIAL_CONFIG.margin.left - INITIAL_CONFIG.margin.right,
        },
        ranges: {
            x: isVertical
                ? [INITIAL_CONFIG.margin.left, _width - INITIAL_CONFIG.margin.right]
                : [INITIAL_CONFIG.margin.top, _height - INITIAL_CONFIG.margin.bottom],
            y: isVertical
                ? [_height - INITIAL_CONFIG.margin.bottom, INITIAL_CONFIG.margin.top]
                : [INITIAL_CONFIG.margin.left, _width - INITIAL_CONFIG.margin.right],
        },
        gridlineTickSize: isVertical
            ? _width - INITIAL_CONFIG.margin.left + INITIAL_CONFIG.spacing.yLabel - INITIAL_CONFIG.margin.right
            : _height - INITIAL_CONFIG.margin.bottom - INITIAL_CONFIG.margin.top,
        transforms: {
            x: isVertical
                ? `translate(0,${_height - INITIAL_CONFIG.margin.bottom})`
                : `translate(${INITIAL_CONFIG.margin.left},0)`,
            y: isVertical ? `translate(${INITIAL_CONFIG.margin.left},0)` : `translate(0,${INITIAL_CONFIG.margin.top})`,
            yGrid: isVertical
                ? `translate(${INITIAL_CONFIG.margin.left - INITIAL_CONFIG.spacing.yLabel},0)`
                : `translate(0,${INITIAL_CONFIG.margin.top})`,
        },
        axisFn: {
            x: isVertical ? d3.axisBottom : d3.axisLeft,
            y: isVertical ? d3.axisLeft : d3.axisTop,
        },
    }
}
// Shamelessly inspired by https://gist.github.com/skokenes/6fa266f4f50c86f77ceabcd6dfca9e42
export const createRoundedRectPath = (
    x: number,
    y: number,
    width: number,
    height: number,
    radius: number,
    position: 'top' | 'right' | 'bottom' | 'left'
): string => {
    // if empty width/height
    const isEmpty =
        (height === 0 && ['top', 'bottom'].includes(position)) || (width === 0 && ['left', 'right'].includes(position))

    const radii = {
        tl: !isEmpty && ['top', 'left'].includes(position) ? radius : 0,
        tr: !isEmpty && ['top', 'right'].includes(position) ? radius : 0,
        bl: !isEmpty && ['bottom', 'left'].includes(position) ? radius : 0,
        br: !isEmpty && ['bottom', 'right'].includes(position) ? radius : 0,
    }

    return (
        // Move to position, offset by radius in x direction
        'M' +
        (x + radii.tl + ',' + y) +
        // Draw a horizontal line to the top right curve start
        'h' +
        (width - radii.tl - radii.tr) +
        // Draw the top right corner curve
        'a' +
        radii.tr +
        ',' +
        radii.tr +
        ' 0 0 1 ' +
        radii.tr +
        ',' +
        radii.tr +
        // Draw a vertical line to the bottom right corner
        'v' +
        (height - radii.tr - radii.br) +
        // Draw the bottom right corner curve
        'a' +
        radii.br +
        ',' +
        radii.br +
        ' 0 0 1 ' +
        -radii.br +
        ',' +
        radii.br +
        // Draw a horizontal line to the bottom left corner
        'h' +
        (radii.br + radii.bl - width) +
        // Draw the bottom left corner
        'a' +
        -radii.bl +
        ',' +
        -radii.bl +
        ' 0 0 1 ' +
        -radii.bl +
        ',' +
        -radii.bl +
        // Draw a vertical line to the top left corner
        'v' +
        (radii.bl + radii.tl - height) +
        // Draw the top left corner
        'a' +
        radii.tl +
        ',' +
        -radii.tl +
        ' 0 0 1 ' +
        radii.tl +
        ',' +
        -radii.tl +
        // Close the shape
        'z'
    )
}

export interface D3HistogramDatum extends HistogramDatum {
    labelWidth?: number
    labelHeight?: number
    shouldShowInBar?: boolean
}
