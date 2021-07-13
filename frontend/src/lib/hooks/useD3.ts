import React, { MutableRefObject, useEffect } from 'react'
import * as d3 from 'd3'

export type D3Selector = d3.Selection<SVGElement, Record<string, unknown>, HTMLElement, any>

export const useD3 = (
    renderChartFn: (svg: D3Selector) => void,
    dependencies: any[] = []
): MutableRefObject<any> | null => {
    const ref = React.useRef()

    useEffect(() => {
        renderChartFn(d3.select(ref.current))
        return () => {}
    }, dependencies)
    return ref
}
