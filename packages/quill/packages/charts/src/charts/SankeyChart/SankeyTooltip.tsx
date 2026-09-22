import React from 'react'

import { TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'
import type { SankeyTooltipContext } from './types'

export interface SankeyTooltipProps<NodeMeta = unknown, LinkMeta = NodeMeta> {
    ctx: SankeyTooltipContext<NodeMeta, LinkMeta>
    valueFormatter?: (value: number) => React.ReactNode
}

function defaultFormatter(value: number): string {
    return value.toLocaleString()
}

function formatShare(fraction: number): string {
    return `${Math.round(fraction * 1000) / 10}%`
}

/** Default tooltip: the node label, or `source → target` for a ribbon, then the value and its
 *  share of the total inflow. */
export function SankeyTooltip<NodeMeta = unknown, LinkMeta = NodeMeta>({
    ctx,
    valueFormatter = defaultFormatter,
}: SankeyTooltipProps<NodeMeta, LinkMeta>): React.ReactElement {
    const { hit, total } = ctx
    const title = hit.kind === 'node' ? hit.node.label : `${hit.link.source.label} → ${hit.link.target.label}`
    const value = hit.kind === 'node' ? hit.node.value : hit.link.value
    const color = hit.kind === 'node' ? hit.node.color : hit.link.color
    const share = total > 0 ? value / total : 0

    return (
        <TooltipSurface data-attr="hog-chart-sankey-tooltip">
            <div className="flex items-center gap-2 mb-1">
                <TooltipSwatch color={color} />
                <span className="font-semibold">{title}</span>
            </div>
            <div className="flex items-center gap-2">
                <strong data-attr="hog-chart-tooltip-value">{valueFormatter(value)}</strong>
                {share > 0 ? <span className="opacity-70">({formatShare(share)})</span> : null}
            </div>
        </TooltipSurface>
    )
}
