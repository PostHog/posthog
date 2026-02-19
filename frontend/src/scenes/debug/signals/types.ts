import type * as d3 from 'd3'

// ── Signal data types ──────────────────────────────────────────────────────────

export interface MatchedMetadata {
    parent_signal_id: string
    match_query: string
    reason: string
}

export interface NoMatchMetadata {
    reason: string
    rejected_signal_ids: string[]
}

export type SignalMatchMetadata = MatchedMetadata | NoMatchMetadata

export function isMatchedMetadata(m: SignalMatchMetadata): m is MatchedMetadata {
    return 'parent_signal_id' in m
}

export interface SignalNode {
    signal_id: string
    content: string
    source_product: string
    source_type: string
    source_id: string
    weight: number
    timestamp: string
    extra: Record<string, unknown>
    match_metadata?: SignalMatchMetadata | null
}

export interface ReportData {
    id: string
    title: string | null
    summary: string | null
    status: string
    total_weight: number
    signal_count: number
    created_at: string | null
    updated_at: string | null
}

export interface ReportSignalsResponse {
    report: ReportData | null
    signals: SignalNode[]
}

export interface ReportListResponse {
    count: number
    next: string | null
    previous: string | null
    results: ReportData[]
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
