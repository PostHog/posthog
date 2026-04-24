import { createContext, useContext } from 'react'

import type { ChartDimensions, ChartScales, Series } from './types'

export interface BaseChartContext<Meta = unknown> {
    dimensions: ChartDimensions
    labels: string[]
    series: Series<Meta>[]
    scales: ChartScales
    hoverIndex: number
}

const ChartContext = createContext<BaseChartContext | null>(null)

export function useChart<Meta = unknown>(): BaseChartContext<Meta> {
    const ctx = useContext(ChartContext)

    if (!ctx) {
        throw new Error('useChart must be used inside a chart component (e.g. <LineChart>)')
    }
    return ctx as BaseChartContext<Meta>
}

export { ChartContext }
