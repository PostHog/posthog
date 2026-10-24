import type React from 'react'

import type { ChartTheme, TooltipContext } from '../../core/types'

/** One frame of a call tree: a function, a span name, an LLM step. */
export interface FlameNode<Meta = unknown> {
    /** Stable identity, used for `defaultFocusedId` and to keep the focus across data updates.
     *  Defaults to the path of names from the root, so it only needs setting when sibling names
     *  repeat or the host needs its own key. */
    id?: string
    /** Label drawn on the rectangle and shown in the tooltip. */
    name: string
    /** Total (inclusive) value: the node plus everything under it, for example the time spent in a
     *  function including its callees. Self value is derived as `value` minus the children's
     *  values. Children that add up to more than their parent (concurrent work in a trace) are
     *  scaled down to fit inside it. */
    value: number
    /** The same node's total value in a baseline window. Turns on the diff colors, and the width
     *  uses the larger of `value` and `baselineValue`, so a node that exists in only one window
     *  still gets room. */
    baselineValue?: number
    /** Number of calls or samples behind `value`. Shown in the tooltip, and with `baselineCount`
     *  it gates the diff colors through `config.diff.minCount`. */
    count?: number
    /** Number of calls or samples behind `baselineValue`. */
    baselineCount?: number
    /** Category used for color, for example the service or the package. Nodes that share a group
     *  share a palette color. */
    group?: string
    /** Child frames, drawn under this one. Their order is kept, except that two or more children
     *  under 1% of this node move to the end so they can bundle into one "+N more" cell. */
    children?: FlameNode<Meta>[]
    /** Passed through to the tooltip and the click callbacks. */
    meta?: Meta
}

/** How a node's value compares with its baseline. */
export type FlameChangeKind =
    /** Above the threshold. */
    | 'slower'
    /** Below the threshold. */
    | 'faster'
    /** Within the threshold. */
    | 'similar'
    /** No baseline, or a baseline of zero. */
    | 'new'
    /** A baseline but no current value. */
    | 'gone'
    /** Fewer samples than `config.diff.minCount` on either side. */
    | 'low-sample'
    /** The node has no baseline data at all, and the chart is not comparing. */
    | 'none'

export interface FlameChange {
    kind: FlameChangeKind
    /** `value / baselineValue`, or null when the baseline is missing or zero. */
    ratio: number | null
}

/** A node as the chart resolved it, handed to the tooltip and the callbacks. */
export interface FlameNodeDatum<Meta = unknown> {
    id: string
    name: string
    /** Total (inclusive) value. */
    value: number
    /** `value` minus the children's values, floored at 0. */
    self: number
    baselineValue?: number
    count?: number
    baselineCount?: number
    group?: string
    meta?: Meta
    /** 0 for a root. */
    depth: number
    /** Null for a root. */
    parentId: string | null
    /** `value` as a share of the parent's value, 0..1. A root's parent is the whole graph. */
    fractionOfParent: number
    /** `value` as a share of all the roots' values, 0..1. */
    fractionOfRoot: number
    change: FlameChange
    /** The node as passed in, with its children. */
    node: FlameNode<Meta>
}

/** Several small sibling nodes drawn as one "+N more" cell. */
export interface FlameBundleDatum<Meta = unknown> {
    /** The parent the bundled nodes share, or null for a bundle of roots. */
    parent: FlameNodeDatum<Meta> | null
    /** Number of bundled nodes. */
    count: number
    /** The bundled nodes, resolved on first read. */
    readonly nodes: FlameNodeDatum<Meta>[]
    /** Every node in the bundle, including the nodes under them. */
    descendantCount: number
    /** Sum of the bundled nodes' values. */
    value: number
}

export type FlameHit<Meta = unknown> =
    | { kind: 'node'; node: FlameNodeDatum<Meta> }
    | { kind: 'bundle'; bundle: FlameBundleDatum<Meta> }

export type FlameColorBy = 'auto' | 'group' | 'name' | 'diff'

export interface FlameDiffConfig {
    /** Relative change, 0..1, below which a node reads as similar: 0.1 colors a node when it is
     *  more than 10% slower or faster. Defaults to 0.1. */
    threshold?: number
    /** Nodes with fewer samples than this, in `count` or `baselineCount`, stay neutral, because a
     *  percentage on a handful of samples is noise. Nodes without counts are never gated.
     *  Defaults to 0 (off). */
    minCount?: number
    /** Color for nodes whose value grew. Defaults to the red in the theme palette (`theme.colors[4]`). */
    slowerColor?: string
    /** Color for nodes whose value shrank. Defaults to the blue in the theme palette (`theme.colors[0]`). */
    fasterColor?: string
}

export interface FlameGraphConfig {
    /** `group` gives each `node.group` a palette color. `name` does the same by node name, so one
     *  function keeps one color wherever it appears. `diff` colors by change against
     *  `baselineValue` on a red-blue scale. `auto` (default) picks `diff` when any node has a
     *  `baselineValue`, else `group` when any node has a `group`, else `name`. */
    colorBy?: FlameColorBy
    diff?: FlameDiffConfig
    /** Formats values in the tooltip. Defaults to `toLocaleString`. */
    valueFormatter?: (value: number) => string
    /** Row height in px. Defaults to 22. */
    rowHeight?: number
    /** `auto` (default) grows with the tree up to `maxHeight`, then scrolls. `fill` takes the
     *  parent's height, which must be set, and scrolls inside it. A number fixes the height in px. */
    height?: 'auto' | 'fill' | number
    /** Cap for `height: 'auto'`, in px. Defaults to 480. */
    maxHeight?: number
    /** `top-down` (default) draws the roots at the top, as an icicle chart. `bottom-up` draws them
     *  at the bottom, as a classic flame graph. */
    direction?: 'top-down' | 'bottom-up'
    /** Zoom into a node on click. Defaults to true. */
    clickToFocus?: boolean
    /** Show the breadcrumb row with the focus path and a reset button. Defaults to true. */
    showBreadcrumb?: boolean
    /** Show the color legend under the graph, for `group` and `diff` colors. Defaults to true. */
    showLegend?: boolean
    tooltip?: {
        /** Show the tooltip on hover. Defaults to true. */
        enabled?: boolean
    }
}

/** Tooltip context for a flame graph hover. `seriesData` holds one row for the hovered node so the
 *  base tooltip helpers keep working. */
export type FlameTooltipContext<Meta = unknown> = TooltipContext<Meta> & {
    hit: FlameHit<Meta>
    /** Formats values the same way as the built-in tooltip. */
    valueFormatter: (value: number) => string
    /** True when the chart compares against a baseline (`diff` colors). */
    comparing: boolean
    /** True when a click on the hovered cell zooms into it. */
    canFocus: boolean
    /** Sum of the roots' values, the whole the shares are taken of. */
    totalValue: number
}

export interface FlameGraphProps<Meta = unknown> {
    /** One root, or several roots drawn side by side. */
    data: FlameNode<Meta> | FlameNode<Meta>[]
    theme: ChartTheme
    config?: FlameGraphConfig
    /** Case-insensitive substring matched against node names. Matches keep their color, the rest
     *  dims, and the breadcrumb row shows the match count and share. */
    search?: string
    /** Node to zoom into on mount, and again whenever this prop changes. Pass `null` to reset. */
    defaultFocusedId?: string | null
    /** Replaces the tooltip content. */
    tooltip?: (ctx: FlameTooltipContext<Meta>) => React.ReactNode
    /** Fires on a click on a node, after any zoom. Not fired for "+N more" cells, which zoom. */
    onNodeClick?: (node: FlameNodeDatum<Meta>) => void
    /** Fires when the zoom changes through a click, the breadcrumb, the reset button or Escape.
     *  `null` means the whole graph is in view. */
    onFocusChange?: (node: FlameNodeDatum<Meta> | null) => void
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}
