import type React from 'react'

import type { ChartTheme, TooltipContext } from '../../core/types'

export interface FlameNode<Meta = unknown> {
    /** Defaults to the path of names from the root. Only the first node with a given id keeps it. */
    id?: string
    name: string
    /** Inclusive of children. Children that add up to more than this are scaled down to fit. */
    value: number
    /** Turns on diff colors. Width uses the larger of `value` and `baselineValue`. */
    baselineValue?: number
    /** Samples behind `value`, for `config.diff.minCount`. */
    count?: number
    baselineCount?: number
    /** Nodes in the same group share a color. */
    group?: string
    /** Fills this node alone, for example to flag an error. Ignored when comparing. */
    color?: string
    /** Two or more children under 1% of this node move to the end so they can bundle. */
    children?: FlameNode<Meta>[]
    meta?: Meta
}

export type FlameChangeKind =
    | 'slower'
    | 'faster'
    | 'similar'
    /** No baseline, or a baseline of zero. */
    | 'new'
    | 'gone'
    /** Fewer samples than `config.diff.minCount` on either side. */
    | 'low-sample'
    /** No baseline data, and the chart is not comparing. */
    | 'none'

export interface FlameChange {
    kind: FlameChangeKind
    /** `value / baselineValue`, or null when the baseline is missing or zero. */
    ratio: number | null
}

export interface FlameNodeDatum<Meta = unknown> {
    id: string
    name: string
    value: number
    self: number
    baselineValue?: number
    count?: number
    baselineCount?: number
    group?: string
    meta?: Meta
    depth: number
    parentId: string | null
    /** 0..1. A root's parent is the whole graph. */
    fractionOfParent: number
    fractionOfRoot: number
    change: FlameChange
    node: FlameNode<Meta>
}

/** Small siblings drawn as one "+N more" cell. */
export interface FlameBundleDatum<Meta = unknown> {
    /** Null for a bundle of roots. */
    parent: FlameNodeDatum<Meta> | null
    count: number
    /** Resolved on first read. */
    readonly nodes: FlameNodeDatum<Meta>[]
    descendantCount: number
    value: number
}

export type FlameHit<Meta = unknown> =
    | { kind: 'node'; node: FlameNodeDatum<Meta> }
    | { kind: 'bundle'; bundle: FlameBundleDatum<Meta> }

export interface FlameDiffConfig {
    /** Relative change below which a node reads as similar. Defaults to 0.1. */
    threshold?: number
    /** Nodes with fewer samples stay neutral; nodes without counts are never gated. Defaults to 0. */
    minCount?: number
}

export interface FlameGraphConfig {
    diff?: FlameDiffConfig
    valueFormatter?: (value: number) => string
    /** Grows with the tree up to this height, then scrolls. Defaults to 480. */
    maxHeight?: number
    /** A color per group, so a host can match its other views. Groups left out take palette colors. */
    groupColors?: Record<string, string>
}

export type FlameTooltipContext<Meta = unknown> = TooltipContext<Meta> & {
    hit: FlameHit<Meta>
    valueFormatter: (value: number) => string
    comparing: boolean
    /** True when clicking the hovered cell zooms into it. */
    canFocus: boolean
}

export interface FlameGraphProps<Meta = unknown> {
    /** One root, or several drawn side by side. */
    data: FlameNode<Meta> | FlameNode<Meta>[]
    theme?: ChartTheme
    config?: FlameGraphConfig
    /** Case-insensitive match on node names. Non-matches dim. */
    search?: string
    /** Read on mount only, and scrolled to the top of the viewport; give the chart a new `key` to open on another node. */
    defaultFocusedId?: string | null
    tooltip?: (ctx: FlameTooltipContext<Meta>) => React.ReactNode
    /** Called when a click, a breadcrumb, Escape or reset changes the zoom, with null for no zoom. */
    onFocusChange?: (focused: FlameHit<Meta> | null) => void
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}
