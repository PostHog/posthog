import { useMemo, useState } from 'react'

import type { TimeRange } from '../dashboard/dashboardTypes'
import type { QuickRange } from './timeRanges'

export interface TimeRangeController {
    /** Undefined shows the dashboard's saved range. */
    value: TimeRange | undefined
    onChange: (time: TimeRange | undefined) => void
    ranges?: QuickRange[]
    /** The project's timezone, which a saved time without an offset is in. Left out, it is the browser's. */
    timezone?: string
}

/**
 * Keeps the viewer's range in component state, for a host with nowhere else to keep it. A host that keeps it in the
 * URL or its own logic builds a `TimeRangeController` itself instead.
 */
export function useTimeRangeController(ranges?: QuickRange[], timezone?: string): TimeRangeController {
    const [value, setValue] = useState<TimeRange | undefined>()
    return useMemo(() => ({ value, onChange: setValue, ranges, timezone }), [value, ranges, timezone])
}
