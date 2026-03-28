import { createContext, useContext } from 'react'

import type { ChartDimensions, ChartScales, Series } from './types'

export interface BaseChartContext {
    dimensions: ChartDimensions
    labels: string[]
    series: Series[]
    scales: ChartScales
    hoverIndex: number
}

const ChartContext = createContext<BaseChartContext | null>(null)

export function useChart<T extends BaseChartContext = BaseChartContext>(): T {
    const ctx = useContext(ChartContext)

    if (!ctx) {
        throw new Error('useChart must be used inside a chart component (e.g. <LineChart>)')
    }
    return ctx as T
}

export { ChartContext }
