import { useMemo } from 'react'

import { normalizeAxisLabel } from '../../utils/axis-labels'
import { DEFAULT_Y_AXIS_ID } from '../types'
import type { YAxis } from '../types'

export interface YAxisMaps {
    /** Per-axis tick formatters keyed by axis id — only axes that define one. Absent when no axis does. */
    formatters?: Record<string, (value: number) => string>
    /** Per-axis side keyed by axis id. */
    positions?: Record<string, 'left' | 'right'>
    /** Per-axis titles keyed by axis id; single-axis charts fall back to the scalar `yAxisLabel`. */
    titles: Record<string, string>
}

/** Per-axis tick formatters, sides, and titles keyed by axis id (formatters/sides are absent for
 *  single-axis charts). */
export function useYAxisMaps(yAxes: YAxis[] | undefined, yAxisLabel?: string): YAxisMaps {
    return useMemo(() => {
        if (!yAxes) {
            const label = normalizeAxisLabel(yAxisLabel)
            const titles: Record<string, string> = {}
            if (label) {
                titles[DEFAULT_Y_AXIS_ID] = label
            }
            return { titles }
        }
        const formatters: Record<string, (value: number) => string> = {}
        const positions: Record<string, 'left' | 'right'> = {}
        const titles: Record<string, string> = {}
        for (const axis of yAxes) {
            if (axis.tickFormatter) {
                formatters[axis.id] = axis.tickFormatter
            }
            positions[axis.id] = axis.position
            const label = normalizeAxisLabel(axis.label)
            if (label) {
                titles[axis.id] = label
            }
        }
        return {
            formatters: Object.keys(formatters).length > 0 ? formatters : undefined,
            positions,
            titles,
        }
    }, [yAxes, yAxisLabel])
}
