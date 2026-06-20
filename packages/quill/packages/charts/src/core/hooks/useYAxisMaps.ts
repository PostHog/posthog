import { useMemo } from 'react'

import type { YAxis } from '../types'

export interface YAxisMaps {
    /** Per-axis tick formatters keyed by axis id — only axes that define one. Absent when no axis does. */
    formatters?: Record<string, (value: number) => string>
    /** Per-axis side keyed by axis id. */
    positions?: Record<string, 'left' | 'right'>
    /** Title of the right-side axis, if any. */
    labelRight?: string
}

/** Derive the per-axis lookup maps the base chart's margins, labels, and titles need from the
 *  resolved axes. All fields are absent for single-axis charts (`yAxes` omitted). */
export function useYAxisMaps(yAxes: YAxis[] | undefined): YAxisMaps {
    return useMemo(() => {
        if (!yAxes) {
            return {}
        }
        const formatters: Record<string, (value: number) => string> = {}
        const positions: Record<string, 'left' | 'right'> = {}
        for (const axis of yAxes) {
            if (axis.tickFormatter) {
                formatters[axis.id] = axis.tickFormatter
            }
            positions[axis.id] = axis.position
        }
        return {
            formatters: Object.keys(formatters).length > 0 ? formatters : undefined,
            positions,
            labelRight: yAxes.find((axis) => axis.position === 'right')?.label,
        }
    }, [yAxes])
}
