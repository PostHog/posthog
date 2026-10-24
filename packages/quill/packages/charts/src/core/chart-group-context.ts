import { createContext } from 'react'

import type { ChartGroupRange } from './chart-group'
import type { ChartGroupStore } from './chart-group-store'

export type ChartGroupTooltipMode = 'hovered' | 'all'

export interface ChartGroupContextValue {
    store: ChartGroupStore
    syncCrosshair: boolean
    syncTooltip: ChartGroupTooltipMode
    syncSelection: boolean
    /** Set only when the group has an `onZoom`, so members know to turn drag-to-zoom on. */
    zoom: ((range: ChartGroupRange) => void) | null
    /** Called when a member's brush completes. */
    select: (range: ChartGroupRange) => void
}

export const ChartGroupContext = createContext<ChartGroupContextValue | null>(null)
