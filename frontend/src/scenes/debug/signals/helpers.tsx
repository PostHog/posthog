import type { GraphEdge, SignalNode } from './types'
import { isMatchedMetadata } from './types'

// ── UI components ──────────────────────────────────────────────────────────────

/** Small triangle of grip dots for corner resize handles. Set `flip` to mirror horizontally. */
export function ResizeGripDots({ flip }: { flip?: boolean }): JSX.Element {
    return (
        <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            className="text-muted opacity-60"
            style={flip ? { transform: 'scaleX(-1)' } : undefined}
        >
            <circle cx="1.5" cy="8.5" r="1" fill="currentColor" />
            <circle cx="5" cy="8.5" r="1" fill="currentColor" />
            <circle cx="5" cy="5" r="1" fill="currentColor" />
            <circle cx="8.5" cy="8.5" r="1" fill="currentColor" />
            <circle cx="8.5" cy="5" r="1" fill="currentColor" />
            <circle cx="8.5" cy="1.5" r="1" fill="currentColor" />
        </svg>
    )
}

// ── Edge builder ───────────────────────────────────────────────────────────────

export function buildEdges(signals: SignalNode[]): GraphEdge[] {
    const signalIds = new Set(signals.map((s) => s.signal_id))
    const edges: GraphEdge[] = []
    for (const signal of signals) {
        const mm = signal.match_metadata
        if (mm && isMatchedMetadata(mm) && signalIds.has(mm.parent_signal_id)) {
            edges.push({
                source: mm.parent_signal_id,
                target: signal.signal_id,
                match_query: mm.match_query,
                reason: mm.reason,
            })
        }
    }
    return edges
}

// ── Color helpers ──────────────────────────────────────────────────────────────

function sourceProductHue(product: string): number {
    let hash = 0
    for (let i = 0; i < product.length; i++) {
        hash = product.charCodeAt(i) + ((hash << 5) - hash)
    }
    return Math.abs(hash) % 360
}

const SOURCE_PRODUCT_COLORS = [
    'var(--primary)',
    'var(--danger)',
    'var(--warning)',
    'var(--success)',
    'var(--purple)',
    'var(--link)',
] as const

export function sourceProductColor(product: string): string {
    return SOURCE_PRODUCT_COLORS[sourceProductHue(product) % SOURCE_PRODUCT_COLORS.length]
}

// ── Geometry helpers ───────────────────────────────────────────────────────────

/** Compute the intersection of a ray from the center of a rectangle to a distant point. */
export function rectEdgePoint(
    cx: number,
    cy: number,
    hw: number,
    hh: number,
    targetX: number,
    targetY: number
): { x: number; y: number } {
    const dx = targetX - cx
    const dy = targetY - cy
    if (dx === 0 && dy === 0) {
        return { x: cx + hw, y: cy }
    }
    const absDx = Math.abs(dx) || 0.001
    const absDy = Math.abs(dy) || 0.001
    const tX = hw / absDx
    const tY = hh / absDy
    const t = Math.min(tX, tY)
    return { x: cx + dx * t, y: cy + dy * t }
}

// ── Status helpers ─────────────────────────────────────────────────────────────

export function statusBadgeColor(status: string): string {
    switch (status) {
        case 'ready':
            return 'bg-success-highlight text-success'
        case 'failed':
            return 'bg-danger-highlight text-danger'
        case 'in_progress':
            return 'bg-warning-highlight text-warning'
        case 'pending_input':
            return 'bg-warning-highlight text-warning'
        case 'candidate':
            return 'bg-primary-highlight text-primary'
        default:
            return 'bg-border text-muted'
    }
}
