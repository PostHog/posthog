import { useMemo } from 'react'

import { autoFormatterFor } from '../scales'
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
