import type React from 'react'

import type { ChartMargins, ChartTheme, TooltipContext } from '../../core/types'
import type { SankeyLinkDatum, SankeyLinkInput, SankeyNodeAlign, SankeyNodeDatum, SankeyNodeInput } from './sankey-data'

/** What the cursor is over, with the laid-out datum attached. */
export type SankeyTooltipHit<NodeMeta = unknown, LinkMeta = NodeMeta> =
    | { kind: 'node'; node: SankeyNodeDatum<NodeMeta> }
    | { kind: 'link'; link: SankeyLinkDatum<NodeMeta, LinkMeta> }

/** Tooltip context for a Sankey hover: the base `TooltipContext` (one `seriesData` row for the
 *  hovered node or ribbon) plus the resolved `hit` and the graph `total` for share math. */
export type SankeyTooltipContext<NodeMeta = unknown, LinkMeta = NodeMeta> = TooltipContext<NodeMeta | LinkMeta> & {
    hit: SankeyTooltipHit<NodeMeta, LinkMeta>
    total: number
}

export interface SankeyChartConfig {
    /** Node rectangle width in px. Defaults to 12. */
    nodeWidth?: number
    /** Vertical gap between nodes in one column, in px. Defaults to 8. */
    nodePadding?: number
    /** Column placement for flows that end early. `justify` (default) pushes terminal nodes to the
     *  last column; `left` keeps every node at its own depth, which is the right choice when the
     *  columns are stages (first tool, second tool, …). */
    nodeAlign?: SankeyNodeAlign
    /** Keep nodes in input order within each column instead of ordering them to untangle ribbons. */
    preserveNodeOrder?: boolean
    /** Header text for each column, left to right. Reserves room above the plot. */
    columnLabels?: string[]
    /** Draw each node's label beside it. Defaults to true. */
    showNodeLabels?: boolean
    /** Append the node's value to its label. Defaults to false. */
    showNodeValues?: boolean
    /** Resting ribbon opacity, 0..1. Defaults to 0.4. */
    linkOpacity?: number
    /** Formats values in node labels and the default tooltip. Defaults to `toLocaleString`. */
    valueFormatter?: (value: number) => string
    tooltip?: {
        /** Show the tooltip on hover. Defaults to true. */
        enabled?: boolean
        /** Where the tooltip sits, as on the cartesian charts. Defaults to `cursor`; `follow-data`
         *  anchors it to the hovered node's right edge or the ribbon's midpoint. */
        placement?: 'follow-data' | 'top' | 'cursor'
    }
    /** Per-side margin overrides. Should be referentially stable. */
    margins?: Partial<ChartMargins>
}

export interface SankeyChartProps<NodeMeta = unknown, LinkMeta = NodeMeta> {
    nodes: SankeyNodeInput<NodeMeta>[]
    links: SankeyLinkInput<LinkMeta>[]
    theme: ChartTheme
    config?: SankeyChartConfig
    /** Replaces the default tooltip content. */
    tooltip?: (ctx: SankeyTooltipContext<NodeMeta, LinkMeta>) => React.ReactNode
    onNodeClick?: (node: SankeyNodeDatum<NodeMeta>) => void
    onLinkClick?: (link: SankeyLinkDatum<NodeMeta, LinkMeta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    /** Overlays rendered above the canvas. Read the layout with `useSankeyLayout()`. */
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}
