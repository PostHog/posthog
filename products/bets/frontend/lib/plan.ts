import type { BetsPlanApi, BetsPlanInputApi } from '../generated/api.schemas'

const MIN_DAYS = 2
const MAX_DAYS = 28
const LIMIT_DAYS = 365
const MIN_MDE = 0.1
const MAX_MDE = 100
const Z_FACTOR = 16
const GROUPS = 2

export type PlanField = 'days' | 'mde' | 'audience'

export type PlanDraft = Record<PlanField, string>

export interface IdeaPlan {
    draft: PlanDraft
    input: BetsPlanInputApi | null
    disabledReason: string | null
    audienceMissing: boolean
    warnings: string[]
}

type Spread = Pick<BetsPlanApi, 'mean' | 'variance' | 'weekly'>

export function plannable(plan: Spread): boolean {
    return !!plan.mean && plan.mean > 0 && !!plan.variance && plan.variance > 0
}

function planDays(plan: Spread, mde: number, audience: number): number {
    const effect = (plan.mean ?? 0) * (mde / 100)
    const total = Math.ceil((Z_FACTOR * (plan.variance ?? 0)) / effect ** 2) * GROUPS
    const days = Math.max(Math.ceil(total / Math.max(audience, 1)), MIN_DAYS)
    return plan.weekly ? Math.ceil(days / 7) * 7 : days
}

export function detectableEffect(plan: Spread, days: number, audience: number): number {
    const perGroup = (days * audience) / GROUPS
    return (Math.sqrt((Z_FACTOR * (plan.variance ?? 0)) / perGroup) / (plan.mean ?? 1)) * 100
}

function parse(value: string, whole: boolean): number | null {
    const number = Number(value.trim().replace(',', '.'))
    if (!value.trim() || !Number.isFinite(number) || number <= 0) {
        return null
    }
    return whole ? Math.round(number) : number
}

function formatMde(value: number): string {
    return String(Math.max(Math.round(value * 10) / 10, MIN_MDE))
}

export function initialDraft(plan: BetsPlanApi): PlanDraft {
    return {
        days: plan.days ? String(plan.days) : '',
        mde: plan.mde ? formatMde(plan.mde) : '',
        audience: plan.audience ? String(plan.audience) : '',
    }
}

export function editDraft(draft: PlanDraft, plan: BetsPlanApi, field: PlanField, value: string): PlanDraft {
    const next = { ...draft, [field]: value }
    const days = parse(next.days, true)
    const mde = parse(next.mde, false)
    const audience = parse(next.audience, true)
    if (field === 'days' && days && audience) {
        next.mde = formatMde(detectableEffect(plan, days, audience))
    }
    if (field !== 'days' && mde && audience) {
        next.days = String(planDays(plan, mde, audience))
    }
    return next
}

function disabledReason(days: number | null, mde: number | null, audience: number | null): string | null {
    if (!audience) {
        return 'Enter how many people a day see this change.'
    }
    if (!days || days < MIN_DAYS) {
        return `Run for at least ${MIN_DAYS} days.`
    }
    if (days > LIMIT_DAYS) {
        return `Run for at most ${LIMIT_DAYS} days. Look for a larger change or more people.`
    }
    if (!mde || mde < MIN_MDE) {
        return `Look for a change of at least ${MIN_MDE}%.`
    }
    if (mde > MAX_MDE) {
        return 'This run can only find a change over 100%. Run longer or add more people.'
    }
    return null
}

export function ideaPlan(plan: BetsPlanApi, edited?: PlanDraft): IdeaPlan {
    const draft = edited ?? initialDraft(plan)
    const days = parse(draft.days, true)
    const mde = parse(draft.mde, false)
    const audience = parse(draft.audience, true)
    const reason = disabledReason(days, mde, audience)
    const warnings = [
        plan.weekly && days && days % 7 ? 'Your traffic has a weekly pattern. Whole weeks give a fairer result.' : '',
        days && days > MAX_DAYS ? 'This is longer than 4 weeks.' : '',
    ].filter(Boolean)
    return {
        draft,
        input: reason || !days || !mde || !audience ? null : { days, mde, audience },
        disabledReason: reason,
        audienceMissing: !audience,
        warnings,
    }
}

export function planSummary(plan: BetsPlanApi): string {
    if (!plan.days || !plan.mde) {
        return ''
    }
    return `Planned for ${plan.days} days, to find a change of ${formatMde(plan.mde)}% or more.`
}

export function stepValue(value: string, field: PlanField, direction: 1 | -1): string {
    const step = field === 'mde' ? 0.1 : 1
    const current = parse(value, field !== 'mde') ?? 0
    const next = Math.max(Math.round((current + step * direction) * 10) / 10, step)
    return String(next)
}
