import React, { useMemo, useSyncExternalStore } from 'react'

import { Tooltip } from '../overlays/Tooltip'
import type { ExternalHoverSource } from './hooks/useHoverAnimation'
import type { TooltipConfig, TooltipContext } from './types'

const NO_INDEX = (): number => -1

interface ChartGroupTooltipProps<Meta> {
    source: ExternalHoverSource
    /** The chart's own hover index. A pointer over this chart wins over the group. */
    localHoverIndex: number
    buildTooltipCtx: (index: number, position: { x: number; y: number } | null) => TooltipContext<Meta> | null
    renderTooltip: (ctx: TooltipContext<Meta>) => React.ReactNode
    placement: TooltipConfig['placement']
}

/** The tooltip a chart shows for another chart's hover under `syncTooltip: 'all'`. Subscribes on its
 *  own, so a group hover re-renders this tooltip and not the chart around it. */
export function ChartGroupTooltip<Meta>({
    source,
    localHoverIndex,
    buildTooltipCtx,
    renderTooltip,
    placement,
}: ChartGroupTooltipProps<Meta>): React.ReactElement | null {
    const index = useSyncExternalStore(source.subscribe, source.getIndex, NO_INDEX)
    const context = useMemo(
        () => (index >= 0 && localHoverIndex < 0 ? buildTooltipCtx(index, null) : null),
        [index, localHoverIndex, buildTooltipCtx]
    )
    return context ? <Tooltip context={context} renderTooltip={renderTooltip} placement={placement} /> : null
}
