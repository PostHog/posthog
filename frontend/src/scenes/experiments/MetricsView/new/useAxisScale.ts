import { useCallback } from 'react'
import { valueToXCoordinate } from '../shared/utils'

/**
 * Hook that provides a coordinate transformation function for experiment charts.
 * Encapsulates the logic for converting data values to SVG x coordinates.
 */
export function useAxisScale(
    chartRadius: number,
    viewBoxWidth: number = 800,
    edgeMargin: number = 20
): (value: number) => number {
    return useCallback(
        (value: number) => valueToXCoordinate(value, chartRadius, viewBoxWidth, edgeMargin),
        [chartRadius, viewBoxWidth, edgeMargin]
    )
}
