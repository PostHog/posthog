import type { FleetRow } from '../logics/csmHudSceneLogic'
import { caps, missingProducts } from './account'
import { daysSince } from './format'
import { deriveProjection, ProjectionRow } from './projection'

export interface AttentionScores {
    risk: number
    riskReasons: string[]
    expand: number
    expandReasons: string[]
    quiet: number
    quietReasons: string[]
}

export function attentionScores(account: FleetRow, projection: ProjectionRow | null): AttentionScores {
    const t = account.traits
    const derived = projection ? deriveProjection(projection) : null
    const fc = derived?.forecastedMrr ?? 0
    const mom = derived?.momGrowthPct ?? null
    const health = account.healthScore ?? 0
    const ticketsRaw = t['vitally.custom.supportTickets']
    const tickets = typeof ticketsRaw === 'number' ? ticketsRaw : parseFloat(String(ticketsRaw ?? '0')) || 0
    const accCaps = caps(account)
    const missing = missingProducts(account)
    const arr = fc * 12
    const lastPaymentTs = t.last_payment_date
    const lpDays = typeof lastPaymentTs === 'number' ? daysSince(lastPaymentTs) : null
    const isAnnual = (account.segments as { name?: string }[]).some(
        (s) => typeof s === 'object' && s && s.name === 'Annual Plan'
    )

    let risk = 0
    const riskReasons: string[] = []
    if (health > 0 && health < 7) {
        risk += (7 - health) * 1.5
        riskReasons.push(`health ${health.toFixed(1)}`)
    }
    if (mom != null && mom <= -10) {
        risk += Math.min(20, -mom) / 4
        riskReasons.push(`${mom.toFixed(0)}% MoM`)
    }
    if (tickets > 10) {
        risk += 1.5
        riskReasons.push(`${tickets} tickets`)
    }
    if (accCaps.length > 0) {
        risk += accCaps.length * 1.5
        riskReasons.push(`${accCaps.length} cap${accCaps.length > 1 ? 's' : ''}`)
    }
    // Tiny accounts (<$200 MRR forecast) get zeroed — too small to invest CSM
    // attention against; lots of false positives from junk traits.
    if (fc < 200) {
        risk = 0
    }

    let expand = 0
    const expandReasons: string[] = []
    if (health >= 7) {
        expand += health - 6
        expandReasons.push(`health ${health.toFixed(1)}`)
        if (mom != null && mom >= 0) {
            expand += Math.min(2, mom / 10)
        }
        if (missing.length >= 2) {
            expand += missing.length * 0.6
            expandReasons.push(`missing ${missing.slice(0, 2).join(', ')}`)
        }
        if (!isAnnual && fc >= 1500) {
            expand += 2
            expandReasons.push(`monthly $${Math.round(fc).toLocaleString()}/mo`)
        }
        if (arr >= 30000) {
            expand += 0.5
        }
    }

    let quiet = 0
    const quietReasons: string[] = []
    if (lpDays != null && lpDays >= 30) {
        quiet = lpDays
        quietReasons.push(`${lpDays}d since last payment`)
    }

    return { risk, riskReasons, expand, expandReasons, quiet, quietReasons }
}
