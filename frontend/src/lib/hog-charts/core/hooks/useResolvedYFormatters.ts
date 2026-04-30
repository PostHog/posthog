import { useMemo } from 'react'

import { autoFormatYTick } from '../scales'
import type { ChartScales } from '../types'

type YTickFormatter = (value: number) => string

interface ResolvedYFormatters {
    left: YTickFormatter
    right: YTickFormatter | undefined
}

function autoFormatterFor(ticks: number[]): YTickFormatter {
    const domainMax = ticks.length > 0 ? Math.abs(Math.max(...ticks)) : 1
    return (v: number) => autoFormatYTick(v, domainMax)
}

export function useResolvedYFormatters(
    scales: ChartScales | null,
    yTickFormatter: YTickFormatter | undefined
): ResolvedYFormatters {
    const left = useMemo<YTickFormatter>(
        () => yTickFormatter ?? autoFormatterFor(scales?.yTicks() ?? []),
        [yTickFormatter, scales]
    )

    const right = useMemo<YTickFormatter | undefined>(() => {
        if (yTickFormatter) {
            return yTickFormatter
        }
        const rightAxis = scales?.yAxes && Object.values(scales.yAxes).find((a) => a.position === 'right')
        return rightAxis ? autoFormatterFor(rightAxis.ticks()) : undefined
    }, [yTickFormatter, scales])

    return { left, right }
}
