import type { BetsDetailApi, BetsWriteApi } from '../generated/api.schemas'
import { money } from './format'

export const EMPTY_BET_FORM: BetsWriteApi = {
    title: '',
    statement: '',
    audience: '',
    area: '',
    repository: '',
    goal_metric: '',
    goal_insight: '',
    secondary_metrics: [],
    target: '',
    direction: 'increase',
    unit: '',
    budget_cents: 0,
}

export function formFromExisting(existing: BetsDetailApi): BetsWriteApi {
    return {
        title: existing.title,
        statement: existing.statement,
        audience: existing.audience,
        area: existing.area,
        repository: existing.repository,
        goal_metric: existing.goal_metric,
        goal_insight: existing.goal_insight,
        secondary_metrics: existing.secondary_metrics,
        target: existing.target === null ? '' : String(Number(existing.target)),
        direction: existing.direction === 'decrease' ? 'decrease' : 'increase',
        unit: existing.unit,
        budget_cents: existing.money.allocated_cents,
    }
}

export function changedFields(next: BetsWriteApi, initial: BetsWriteApi): Partial<BetsWriteApi> {
    return Object.fromEntries(
        Object.entries(next).filter(
            ([field, value]) => JSON.stringify(value) !== JSON.stringify(initial[field as keyof BetsWriteApi])
        )
    )
}

export const SERVER_FIELDS: Record<string, BetFormField> = {
    statement: 'statement',
    title: 'title',
    goal_insight: 'goal_insight',
    target: 'target',
    secondary_metrics: 'guardrails',
    budget_cents: 'budget',
    repository: 'repository',
}

export const FIELD_LABELS: Record<BetFormField, string> = {
    statement: 'belief',
    title: 'name',
    goal_insight: 'insight',
    target: 'target',
    guardrails: 'guardrail direction',
    budget: 'budget',
    repository: 'repository',
}

export const MAX_OWNER_IDEAS = 5
export const MAX_GUARDRAILS = 5

export const TARGET_PATTERN = /^-?\d{0,16}(?:\.\d{0,4})?$/
export const REPOSITORY_PATTERN = /^[\w.-]+\/[\w.-]+$/

export type BetFormField = 'statement' | 'title' | 'goal_insight' | 'target' | 'guardrails' | 'budget' | 'repository'

export interface BetInsightOption {
    value: string
    label: string
    disabledReason: string | null
}

export interface BetMissingPart {
    field: BetFormField
    label: string
}

export interface GithubRepositories {
    integrationId: number | null
    only: string | null
}

export type RepositorySource = 'last' | 'only' | null

export interface FormProblemsInput {
    form: BetsWriteApi
    title: string
    ineligibleReason: string | null
    target: number | null
    current: number | null
    budgetCents: number | null
    budgetLimitCents: number | null
    budgetRequired: boolean
    repository: string
    insightNames: Record<string, string>
}

export function formProblems(input: FormProblemsInput): Partial<Record<BetFormField, string>> {
    const { form, title, ineligibleReason, target, current, budgetCents, budgetLimitCents, repository } = input
    const problems: Partial<Record<BetFormField, string>> = {}
    if (!form.statement.trim()) {
        problems.statement = 'Say what you believe will improve.'
    }
    if (!title.trim()) {
        problems.title = 'Give the bet a short name.'
    }
    if (!form.goal_insight) {
        problems.goal_insight = 'Choose the insight that measures this bet.'
    } else if (ineligibleReason) {
        problems.goal_insight = ineligibleReason
    }
    if (!form.target.trim()) {
        problems.target = 'Enter the value you want to reach.'
    } else if (target === null) {
        problems.target = 'Enter a number with up to 4 decimals.'
    } else if (current !== null && target === current) {
        problems.target = 'Pick a target that is different from the current value.'
    }
    const undecided = (form.secondary_metrics ?? []).find((metric) => !metric.direction)
    if (undecided) {
        problems.guardrails = `Choose which way is better for ${
            input.insightNames[undecided.insight] || undecided.name || 'each guardrail'
        }.`
    }
    if (budgetCents === null || (input.budgetRequired && budgetCents === 0)) {
        problems.budget = 'Enter a budget above $0.'
    } else if (budgetLimitCents !== null && budgetCents > budgetLimitCents) {
        problems.budget = `Only ${money(budgetLimitCents)} is left.`
    }
    if (!repository.trim()) {
        problems.repository = 'Choose the repository where Bets opens pull requests.'
    } else if (!REPOSITORY_PATTERN.test(repository.trim())) {
        problems.repository = 'Use the owner/repository form.'
    }
    return problems
}
