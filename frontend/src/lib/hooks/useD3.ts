import { MutableRefObject, useEffect, useRef } from 'react'
import * as d3 from 'd3'

export type D3Selector = d3.Selection<any, any, any, any>
export type D3Transition = d3.Transition<any, any, any, any>

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

export const animate = (
    it: D3Selector,
    transitionDuration: number,
    isAnimated: boolean,
    toAnimate: (_it: D3Transition | D3Selector) => D3Transition | D3Selector = (_it) => _it // everything you want to animate goes here
): D3Transition | D3Selector => {
    if (isAnimated) {
        return it.transition().duration(transitionDuration).call(toAnimate)
    }
    return it.call(toAnimate)
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
