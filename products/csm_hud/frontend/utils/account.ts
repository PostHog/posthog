import type { FleetRow } from '../logics/csmHudSceneLogic'

export interface Cap {
    product: string
    pct: number
    limit: number
    forecast: number
}

export function caps(account: FleetRow): Cap[] {
    const t = account.traits
    const out: Cap[] = []
    for (const k of Object.keys(t)) {
        if (!k.endsWith('_billing_limit')) {
            continue
        }
        const limit = typeof t[k] === 'number' ? (t[k] as number) : parseFloat(String(t[k]))
        if (!Number.isFinite(limit) || limit <= 0) {
            continue
        }
        const product = k.replace('_billing_limit', '')
        const fcRaw = t[`${product}_forecasted_mrr`]
        const fc = typeof fcRaw === 'number' ? fcRaw : parseFloat(String(fcRaw ?? ''))
        if (!Number.isFinite(fc)) {
            continue
        }
        const pct = (fc / limit) * 100
        if (pct >= 70) {
            out.push({ product, pct, limit, forecast: fc })
        }
    }
    return out.sort((a, b) => b.pct - a.pct)
}

const PRODUCTS_TO_CHECK = ['session_replay', 'error_tracking', 'llm_analytics', 'data_warehouse'] as const
const PRODUCT_LABELS: Record<(typeof PRODUCTS_TO_CHECK)[number], string> = {
    session_replay: 'session replay',
    error_tracking: 'error tracking',
    llm_analytics: 'LLM analytics',
    data_warehouse: 'data warehouse',
}

export function missingProducts(account: FleetRow): string[] {
    const t = account.traits
    return PRODUCTS_TO_CHECK.flatMap((p) => {
        const v = t[`${p}_forecasted_mrr`]
        const fc = typeof v === 'number' ? v : parseFloat(String(v ?? ''))
        return Number.isFinite(fc) && fc > 0 ? [] : [PRODUCT_LABELS[p]]
    })
}

interface Segment {
    name?: string
}

function segmentNames(account: FleetRow): string[] {
    return account.segments
        .map((s) => (typeof s === 'object' && s ? ((s as Segment).name ?? '') : ''))
        .filter((n): n is string => typeof n === 'string' && n.length > 0)
}

export function planType(account: FleetRow): 'Annual' | 'Monthly' {
    return segmentNames(account).includes('Annual Plan') ? 'Annual' : 'Monthly'
}

export function tier(account: FleetRow): 'Enterprise' | 'Teams' | 'Boost' | 'YC active' | null {
    const segs = segmentNames(account)
    if (segs.includes('Enterprise Plan')) {
        return 'Enterprise'
    }
    if (segs.includes('Teams Plan')) {
        return 'Teams'
    }
    if (segs.includes('Boost Plan')) {
        return 'Boost'
    }
    if (segs.some((s) => s.startsWith('YC Plan - Active'))) {
        return 'YC active'
    }
    return null
}
