import { daysUntil } from './format'

const MS_PER_DAY = 86_400_000

export interface ProjectionRow {
    externalId: string
    name: string
    currentMonthSpend: number
    priorMonthMrr: number
    m2Actual: number
    m3Actual: number
    m1Paid: number | null
    m2Paid: number | null
    m3Paid: number | null
    weightedBaseline: number
    forecastedMrr: number
    historyMonths: number
    isPrepaidCreditAcct: boolean
    mtdStripe: number | null
    lastChargeUsd: number | null
    lastChargeDate: string | null
    lastChargeStatus: string | null
    periodStarts: string | null
    periodEnds: string | null
    contractStart: string | null
    contractEnd: string | null
    termMonths: number | null
    arrDiscounted: number | null
    opportunityName: string | null
    csm: string | null
    ae: string | null
    managedBy: string | null
}

export interface ParsedPeriod {
    periodStarts: Date
    periodEnds: Date
    daysInPeriod: number
    dayOfPeriod: number
    daysRemaining: number
}

export interface DerivedProjection extends ProjectionRow {
    daysInCurrentMonth: number
    todayDay: number
    daysRemaining: number
    dailyRate: number
    momGrowthPct: number | null
    hasBillingPeriod: boolean
}

export function parsePeriod(starts: string | null, ends: string | null): ParsedPeriod | null {
    if (!starts || !ends) {
        return null
    }
    const start = new Date(starts)
    const end = new Date(ends)
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
        return null
    }
    const daysInPeriod = Math.max(1, Math.round((end.getTime() - start.getTime()) / MS_PER_DAY))
    const dayOfPeriod = Math.max(0, Math.min(daysInPeriod, Math.round((Date.now() - start.getTime()) / MS_PER_DAY)))
    return {
        periodStarts: start,
        periodEnds: end,
        daysInPeriod,
        dayOfPeriod,
        daysRemaining: Math.max(0, daysInPeriod - dayOfPeriod),
    }
}

export function deriveProjection(p: ProjectionRow): DerivedProjection {
    const period = parsePeriod(p.periodStarts, p.periodEnds)
    const today = new Date()
    const calendarDaysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate()
    const calendarTodayDay = today.getDate()
    const daysInCurrentMonth = period ? period.daysInPeriod : calendarDaysInMonth
    const todayDay = period ? period.dayOfPeriod : calendarTodayDay
    const daysRemaining = period ? period.daysRemaining : calendarDaysInMonth - calendarTodayDay
    const dailyRate = p.weightedBaseline > 0 ? p.weightedBaseline / daysInCurrentMonth : 0
    const momGrowthPct = p.priorMonthMrr > 0 ? ((p.forecastedMrr - p.priorMonthMrr) / p.priorMonthMrr) * 100 : null
    return {
        ...p,
        daysInCurrentMonth,
        todayDay,
        daysRemaining,
        dailyRate,
        momGrowthPct,
        hasBillingPeriod: !!period,
    }
}

export interface MtdSplit {
    credit: number
    cash: number
    total: number
    mode: 'cash' | 'credit' | 'mixed'
}

export function mtdSplit(
    p: ProjectionRow | null,
    accountTraits: Record<string, unknown> | null | undefined
): MtdSplit | null {
    if (!p) {
        return null
    }
    const total = p.currentMonthSpend || 0
    if (total <= 0) {
        return null
    }
    const balanceTrait = accountTraits?.['stripe.accountBalance']
    const balance = typeof balanceTrait === 'number' ? Math.max(0, -balanceTrait) : 0
    const credit = Math.min(total, balance)
    const cash = Math.max(0, total - credit)
    let mode: MtdSplit['mode'] = 'mixed'
    if (credit <= 0.01) {
        mode = 'cash'
    } else if (cash <= 0.01) {
        mode = 'credit'
    }
    return { credit, cash, total, mode }
}

export interface CreditPattern {
    kind: 'cash-to-credit' | 'mixed-to-credit'
    label: string
    tooltip: string
}

export function creditPattern(p: ProjectionRow | null, split: MtdSplit | null): CreditPattern | null {
    if (!p || !split || split.mode === 'cash') {
        return null
    }
    const creditShare = split.total > 0 ? split.credit / split.total : 0
    if (creditShare < 0.8) {
        return null
    }
    const paidHistory = [p.m1Paid, p.m2Paid, p.m3Paid].map((v) => Number(v) || 0)
    const hadCash = paidHistory.some((v) => v > 0)
    if (!hadCash) {
        return null
    }
    if (paidHistory[0] > 0) {
        return {
            kind: 'cash-to-credit',
            label: 'CR SHIFT',
            tooltip:
                'Last invoice was paid in cash; current period is funded almost entirely from credits. Watch for credit balance drawdown.',
        }
    }
    return {
        kind: 'mixed-to-credit',
        label: 'CR DRAW',
        tooltip: 'Earlier invoices had cash component; current period is funded almost entirely from credits.',
    }
}

export interface Renewal {
    billingPeriodStart: string | null
    billingPeriodEnd: string | null
    contractStart: string | null
    contractEnd: string | null
    daysUntilRenewal: number | null
    daysUntilContractEnd: number | null
    termMonths: number | null
    arrDiscounted: number | null
    opportunityName: string | null
    csm: string | null
    ae: string | null
    managedBy: string | null
}

export function renewal(p: ProjectionRow | null): Renewal | null {
    if (!p || (!p.periodEnds && !p.contractEnd)) {
        return null
    }
    return {
        billingPeriodStart: p.periodStarts,
        billingPeriodEnd: p.periodEnds,
        contractStart: p.contractStart,
        contractEnd: p.contractEnd,
        daysUntilRenewal: daysUntil(p.periodEnds),
        daysUntilContractEnd: daysUntil(p.contractEnd),
        termMonths: p.termMonths,
        arrDiscounted: p.arrDiscounted,
        opportunityName: p.opportunityName,
        csm: p.csm,
        ae: p.ae,
        managedBy: p.managedBy,
    }
}
