import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { CADENCE_LABELS } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import { checkDisplayName } from 'products/data_quality/frontend/checksConstants'
import { DataQualityOverviewCheckApi } from 'products/data_quality/frontend/generated/api.schemas'

import type { AttentionSubject, MaterializationProblem } from './modelsOverviewLogic'
import type { AttentionModel } from './modelsSceneLogic'
import { servingSuspension } from './suspension'

export type IssueTone = 'danger' | 'warning'

export type IssueKind = MaterializationProblem['kind'] | 'checks'

export interface IssueStatus {
    kind: IssueKind
    label: string
    tone: IssueTone
    tooltip: string
}

export const ISSUE_KIND_ORDER: IssueKind[] = ['suspended', 'failed', 'behind', 'checks']

export const ISSUE_LABELS: Record<IssueKind, string> = {
    suspended: 'Suspended',
    failed: 'Refresh failed',
    behind: 'Stale',
    checks: 'Checks failing',
}

/** Not run statuses: these say whether anything will retry on its own, which is why suspension sorts first. */
const PROBLEM_TOOLTIPS: Record<AttentionModel['problem'], string> = {
    Suspended: 'Scheduled runs have stopped after repeated failures. This model stays behind until you resume it.',
    Failed: 'The last scheduled run failed. The next run will try again.',
}

function cadenceOf(problem: Extract<MaterializationProblem, { kind: 'behind' }>): string {
    return CADENCE_LABELS[problem.behind.node.sync_interval!]
}

export function materializationStatus(problem: MaterializationProblem): IssueStatus {
    if (problem.kind === 'behind') {
        return {
            kind: 'behind',
            label: ISSUE_LABELS.behind,
            tone: 'warning',
            tooltip: `Nothing failed, but this model has gone more than twice its ${cadenceOf(problem)} refresh interval without a run. Its schedule may have stopped.`,
        }
    }
    return {
        kind: problem.kind,
        label: ISSUE_LABELS[problem.kind],
        tone: problem.kind === 'suspended' ? 'danger' : 'warning',
        tooltip: PROBLEM_TOOLTIPS[problem.attention.problem],
    }
}

export function failingChecksStatus(checks: DataQualityOverviewCheckApi[]): IssueStatus {
    return {
        kind: 'checks',
        label: `${pluralize(checks.length, 'check')} failing`,
        tone: 'danger',
        tooltip: checks.map(checkDisplayName).join(', '),
    }
}

export function subjectName(subject: AttentionSubject): string {
    return subject.node?.name ?? subject.failingChecks[0]?.subject_name ?? ''
}

export function subjectDetail(subject: AttentionSubject): string | null {
    const { materialization, failingChecks } = subject
    if (materialization?.kind === 'behind') {
        return `Should refresh every ${cadenceOf(materialization)}`
    }
    if (materialization) {
        return materialization.attention.reason
    }
    const [first, ...rest] = failingChecks
    if (!first) {
        return null
    }
    return rest.length > 0 ? `${checkDisplayName(first)} and ${rest.length} more` : checkDisplayName(first)
}

export function subjectImpact(subject: AttentionSubject): string | null {
    const attention = subject.materialization?.kind === 'behind' ? null : subject.materialization?.attention
    const downstreamCount = attention?.downstreamCount ?? subject.node?.downstream_count ?? 0
    const skippedCount = attention?.skippedCount ?? 0
    const parts = [
        downstreamCount > 0 ? `${pluralize(downstreamCount, 'model')} downstream` : null,
        skippedCount > 0 ? `${pluralize(skippedCount, 'model')} skipped` : null,
    ].filter(Boolean)
    return parts.length > 0 ? parts.join(', ') : null
}

function earliestFailingSince(checks: DataQualityOverviewCheckApi[]): string | null {
    const times = checks.flatMap((check) => (check.failing_since ? [check.failing_since] : []))
    return times.sort()[0] ?? null
}

function startedAt(subject: AttentionSubject): string | null | undefined {
    const { materialization, failingChecks } = subject
    if (materialization?.kind === 'suspended') {
        return servingSuspension(materialization.attention.node.suspended)?.at
    }
    if (materialization?.kind === 'failed') {
        return materialization.attention.node.last_run_at
    }
    return earliestFailingSince(failingChecks)
}

export type SubjectSince = { kind: 'time'; time: string } | { kind: 'overdue'; label: string }

export function subjectSince(subject: AttentionSubject): SubjectSince | null {
    const { materialization } = subject
    if (materialization?.kind === 'behind') {
        return {
            kind: 'overdue',
            label: `${humanFriendlyDuration(materialization.behind.overdueSeconds, { maxUnits: 1 })} overdue`,
        }
    }
    const time = startedAt(subject)
    return time ? { kind: 'time', time } : null
}

const NEXT_STEP_LABELS: Record<MaterializationProblem['kind'], string> = {
    suspended: 'Fix and resume',
    failed: 'View error',
    behind: 'Check schedule',
}

export const REFRESH_LABELS: Record<Exclude<MaterializationProblem['kind'], 'suspended'>, string> = {
    failed: 'Retry',
    behind: 'Run now',
}

export function nextStepLabel(subject: AttentionSubject): string {
    if (subject.materialization) {
        return NEXT_STEP_LABELS[subject.materialization.kind]
    }
    return subject.failingChecks.length > 1 ? 'View checks' : 'View check'
}
