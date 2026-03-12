import * as d3 from 'd3'
import { RefObject, useEffect, useRef } from 'react'

export type D3Selector = d3.Selection<any, any, any, any>
export type D3Transition = d3.Transition<any, any, any, any>

export const useD3 = (
    renderChartFn: (svg: D3Selector) => void,
    dependencies: any[] = []
): RefObject<HTMLDivElement> => {
    const ref = useRef<HTMLDivElement>(null)

    useEffect(
        () => {
            if (ref.current) {
                renderChartFn(d3.select(ref.current))
            }
        },

        dependencies
    )
    return ref
}
