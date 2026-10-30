import type { BetsDetailApi, BetsWriteApi } from '../generated/api.schemas'
import { money } from './format'

export const EMPTY_BET_FORM: BetsWriteApi = {
    title: '',
    statement: '',
    audience: '',
    area: '',
    repository: '',
    repositories: [],
    goal_metric: '',
    goal_insight: '',
    goal_description: '',
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
        repositories: existing.repositories,
        goal_metric: existing.goal_metric,
        goal_insight: existing.goal_insight,
        goal_description: existing.goal_description,
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
    goal_insight: 'measure',
    target: 'target',
    guardrails: 'guardrail direction',
    budget: 'budget',
    repository: 'repository',
}

export const MAX_OWNER_IDEAS = 5
export const MAX_GUARDRAILS = 5

export const TARGET_PATTERN = /^-?\d{0,16}(?:\.\d{0,4})?$/
const REPOSITORY_PATTERN = /^[\w.-]+\/[\w.-]+$/

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

interface FormProblemsInput {
    form: BetsWriteApi
    title: string
    ineligibleReason: string | null
    target: number | null
    current: number | null
    budgetCents: number | null
    budgetLimitCents: number | null
    budgetRequired: boolean
    repositories: string[]
    describing: boolean
    insightNames: Record<string, string>
}

export function formProblems(input: FormProblemsInput): Partial<Record<BetFormField, string>> {
    const { form, title, ineligibleReason, target, current, budgetCents, budgetLimitCents, repositories, describing } =
        input
    const problems: Partial<Record<BetFormField, string>> = {}
    if (!form.statement.trim()) {
        problems.statement = 'Say what you believe will improve.'
    }
    if (!title.trim()) {
        problems.title = 'Give the bet a short name.'
    }
    if (describing) {
        if (!(form.goal_description ?? '').trim()) {
            problems.goal_insight = 'Describe how Bets should measure this bet.'
        }
    } else if (!form.goal_insight) {
        problems.goal_insight = 'Choose the insight that measures this bet.'
    } else if (ineligibleReason) {
        problems.goal_insight = ineligibleReason
    }
    const targetProblem = !(form.target ?? '').trim()
        ? 'Enter the value you want to reach.'
        : target === null
          ? 'Enter a number with up to 4 decimals.'
          : current !== null && target === current
            ? 'Pick a target that is different from the current value.'
            : null
    if (targetProblem && !describing) {
        problems.target = targetProblem
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
    if (!repositories.length) {
        problems.repository = 'Choose the repository where Bets opens pull requests.'
    } else if (repositories.some((repository) => !REPOSITORY_PATTERN.test(repository.trim()))) {
        problems.repository = 'Use the owner/repository form.'
    }
    return problems
}
