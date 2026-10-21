// Types of `SankeyChart`. Shared types it uses, declared in core.d.ts: ChartTheme, ChartMargins, TooltipContext, Series, SeriesType.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': SankeyChart, SankeyChartProps, SankeyNodeInput, SankeyLinkInput, SankeyChartConfig, SankeyTooltipContext, SankeyNodeDatum, SankeyLinkDatum, SankeyTooltipHit, SankeyHighlight, SankeyNodeAlign, SankeyLastColumnLabels.
// Other declarations here are shapes to match, not names to import.

export declare function SankeyChart<NodeMeta = unknown, LinkMeta = NodeMeta>({
    onError,
    ...rest
}: SankeyChartProps<NodeMeta, LinkMeta>): React.ReactElement

export interface SankeyChartProps<NodeMeta = unknown, LinkMeta = NodeMeta> {
    nodes: SankeyNodeInput<NodeMeta>[]
    links: SankeyLinkInput<LinkMeta>[]
    theme: ChartTheme
    config?: SankeyChartConfig
    tooltip?: (ctx: SankeyTooltipContext<NodeMeta, LinkMeta>) => React.ReactNode
    onNodeClick?: (node: SankeyNodeDatum<NodeMeta>) => void
    onLinkClick?: (link: SankeyLinkDatum<NodeMeta, LinkMeta>) => void
    /** Fires when the cursor moves onto a different node or ribbon or a touch tap lands on one, and
     *  with `null` when the cursor leaves the graph, a tap lands on empty space, or the layout
     *  changes. Lets a host drive its own emphasis, for example through `highlight`. */
    onHoverChange?: (hit: SankeyTooltipHit<NodeMeta, LinkMeta> | null) => void
    /** Controlled emphasis. While set, the chart dims everything outside this set and the built-in
     *  hover dimming is off, so the host decides what a hover means (the whole downstream path, a
     *  selection). Pass `null` to hand emphasis back to the hover. */
    highlight?: SankeyHighlight | null
    className?: string
    dataAttr?: string
    /** Overlays rendered above the canvas. Read the layout with `useSankeyLayout()`. */
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

/** A node of the flow graph. `id` must be unique; a node that occurs at several stages of a
 *  flow (the same tool called twice in a row) needs one node per stage, so prefix the id with the
 *  stage. Nodes with the same `label` share a palette color, so the repeated tool still reads
 *  as one thing. */
export interface SankeyNodeInput<Meta = unknown> {
    id: string
    /** Display label. Defaults to `id`. */
    label?: string
    /** CSS color (hex, rgb, or `var(--…)`, resolved by the chart). Omit to pick a palette color
     *  by label. */
    color?: string
    /** Consumer data handed back through tooltips and click handlers. */
    meta?: Meta
    /** Pin the node to this zero-based column. See `column` in docs/chart-types.md for the rules. */
    column?: number
}

/** A directed flow from `source` to `target` (both node ids). The graph must be acyclic. */
export interface SankeyLinkInput<Meta = unknown> {
    source: string
    target: string
    value: number
    /** CSS color for the ribbon. Defaults to the source node's color. */
    color?: string
    /** Consumer data handed back through tooltips and click handlers. */
    meta?: Meta
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
    /** Defaults to true. */
    showNodeLabels?: boolean
    /** Where the last column's labels sit. `inside` (default) puts them left of the nodes, over the
     *  ribbons; `outside` puts them right of the nodes in a reserved margin, so names in the last
     *  column read in full on a narrow chart. */
    lastColumnLabels?: SankeyLastColumnLabels
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
    /** Per-side margin overrides. Should be referentially stable. Column headers add their room to
     *  the top margin, and `outside` labels to the right margin, on top of an override. */
    margins?: Partial<ChartMargins>
}

/** Tooltip context for a Sankey hover: the base `TooltipContext` (one `seriesData` row for the
 *  hovered node or ribbon) plus the resolved `hit` and the graph `total` for share math. */
export type SankeyTooltipContext<NodeMeta = unknown, LinkMeta = NodeMeta> = TooltipContext<NodeMeta | LinkMeta> & {
    hit: SankeyTooltipHit<NodeMeta, LinkMeta>
    total: number
}

export interface SankeyNodeDatum<Meta = unknown> {
    id: string
    label: string
    color: string
    meta?: Meta
    /** Position in the `nodes` prop and in `layout.nodes`. */
    index: number
    column: number
    /** Sum of the larger side's link values (in or out). */
    value: number
    x0: number
    x1: number
    y0: number
    y1: number
}

/** A laid-out link: the input plus the ribbon geometry. `y0` is the centerline y at the source
 *  edge, `y1` at the target edge; `width` is the ribbon thickness. */
export interface SankeyLinkDatum<NodeMeta = unknown, LinkMeta = NodeMeta> {
    source: SankeyNodeDatum<NodeMeta>
    target: SankeyNodeDatum<NodeMeta>
    value: number
    color: string
    meta?: LinkMeta
    /** Position in the `links` prop and in `layout.links`; what `SankeyHighlight.linkIndices` names. */
    index: number
    y0: number
    y1: number
    width: number
}

export type SankeyTooltipHit<NodeMeta = unknown, LinkMeta = NodeMeta> =
    | {
          kind: 'node'
          node: SankeyNodeDatum<NodeMeta>
      }
    | {
          kind: 'link'
          link: SankeyLinkDatum<NodeMeta, LinkMeta>
      }

/** A consumer-chosen part of the graph to keep at full strength while the rest dims. Nodes are
 *  named by id; links by their index in the `links` prop, which the layout keeps. */
export interface SankeyHighlight {
    nodeIds: ReadonlySet<string>
    linkIndices: ReadonlySet<number>
}

/** How nodes spread across columns when a flow ends early. Mirrors d3-sankey's alignments. */
export type SankeyNodeAlign = 'left' | 'right' | 'center' | 'justify'

/** Where the last column's labels go: `inside` sits them left of the nodes, over the ribbons;
 *  `outside` sits them right of the nodes in a margin reserved for them. */
export type SankeyLastColumnLabels = 'inside' | 'outside'
