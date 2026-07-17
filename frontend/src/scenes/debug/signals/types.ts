import type * as d3 from 'd3'

import type {
    MatchedMetadataApi,
    NoMatchMetadataApi,
    SignalMatchMetadataApi,
    SignalNodeApi,
} from 'products/signals/frontend/generated/api.schemas'

// ── Signal data types (aliases of the OpenAPI-generated shapes) ────────────────

export type MatchedMetadata = MatchedMetadataApi
export type NoMatchMetadata = NoMatchMetadataApi
export type SignalMatchMetadata = SignalMatchMetadataApi
export type SignalNode = SignalNodeApi

export function isMatchedMetadata(m: SignalMatchMetadata): m is MatchedMetadata {
    return 'parent_signal_id' in m
}

// ── Layout / graph types ───────────────────────────────────────────────────────

export interface LayoutPosition {
    x: number
    y: number
}

export interface GraphEdge {
    source: string
    target: string
    match_query: string
    reason: string
}

// ── Layout constants ───────────────────────────────────────────────────────────

export const NODE_W = 152
export const NODE_H = 40

// ── Tunable simulation config ──────────────────────────────────────────────────

export interface SimConfig {
    repulsion: number
    springK: number
    springLength: number
    damping: number
    centerGravity: number
    collideRadius: number
}

export const DEFAULT_CONFIG: SimConfig = {
    repulsion: 500,
    springK: 0.08,
    springLength: 200,
    damping: 0.1,
    centerGravity: 0.035,
    collideRadius: 85,
}

// ── Force simulation types ─────────────────────────────────────────────────────

export interface SimNode extends d3.SimulationNodeDatum {
    id: string
}

export interface SimEdge extends d3.SimulationLinkDatum<SimNode> {
    match_query: string
    reason: string
}
