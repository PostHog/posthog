import { useMemo } from 'react'

import { autoFormatYTick } from '../scales'
import type { ChartScales } from '../types'

type YTickFormatter = (value: number) => string

interface ResolvedYFormatters {
    left: YTickFormatter
    right: YTickFormatter | undefined
}

export function useResolvedYFormatters(
    scales: ChartScales | null,
    yTickFormatter: YTickFormatter | undefined
): ResolvedYFormatters {
    const left = useMemo<YTickFormatter>(() => {
        if (yTickFormatter) {
            return yTickFormatter
        }
        const ticks = scales?.yTicks() ?? []
        const domainMax = ticks.length > 0 ? Math.abs(Math.max(...ticks)) : 1
        return (v: number) => autoFormatYTick(v, domainMax)
    }, [yTickFormatter, scales])

    const right = useMemo<YTickFormatter | undefined>(() => {
        if (yTickFormatter) {
            return yTickFormatter
        }
        const rightAxis = scales?.yAxes && Object.values(scales.yAxes).find((a) => a.position === 'right')
        if (!rightAxis) {
            return undefined
        }
        const ticks = rightAxis.ticks()
        const domainMax = ticks.length > 0 ? Math.abs(Math.max(...ticks)) : 1
        return (v: number) => autoFormatYTick(v, domainMax)
    }, [yTickFormatter, scales])

    return { left, right }
}
