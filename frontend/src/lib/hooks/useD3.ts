import { MutableRefObject, useEffect, useRef } from 'react'
import * as d3 from 'd3'

export type D3Selector = d3.Selection<any, unknown, null, undefined>

export const getOrCreateEl = (
    container: D3Selector,
    selector: string,
    createCallback: () => D3Selector
): D3Selector => {
    const el = container.select(selector)
    if (el.empty()) {
        return createCallback()
    }
    return el
}

export const useD3 = (
    renderChartFn: (svg: D3Selector) => void,
    dependencies: any[] = []
): MutableRefObject<any> | null => {
    const ref = useRef<HTMLDivElement>()

    useEffect(() => {
        if (ref.current !== undefined) {
            renderChartFn(d3.select(ref.current))
        }
        return () => {}
    }, dependencies)
    return ref
}
