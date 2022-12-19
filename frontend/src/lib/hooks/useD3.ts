import { MutableRefObject, useEffect, useRef } from 'react'
import * as d3 from 'd3'

export type D3Selector = d3.Selection<any, any, any, any>
export type D3Transition = d3.Transition<any, any, any, any>

export const useD3 = (
    renderChartFn: (svg: D3Selector) => void,
    dependencies: any[] = []
): MutableRefObject<any> | null => {
    const ref = useRef<HTMLDivElement>()

    useEffect(
        () => {
            if (ref.current !== undefined) {
                renderChartFn(d3.select(ref.current))
            }
            return () => {}
        },

        dependencies
    )
    return ref
}
