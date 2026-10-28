import { pluralize } from 'lib/utils/strings'
import { CADENCE_LABELS } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import type { OverviewIssue } from './modelsOverviewLogic'
import type { AttentionModel } from './modelsSceneLogic'

export type IssueTone = 'danger' | 'warning'

export interface IssueStatus {
    label: string
    tone: IssueTone
    tooltip: string
}

/** Not run statuses: these say whether anything will retry on its own, which is why suspension sorts first. */
const PROBLEM_TOOLTIPS: Record<AttentionModel['problem'], string> = {
    Suspended: 'Scheduled runs have stopped after repeated failures. This model stays behind until you resume it.',
    Failed: 'The last scheduled run failed. The next run will try again.',
}

function cadenceOf(issue: Extract<OverviewIssue, { kind: 'behind' }>): string {
    return CADENCE_LABELS[issue.behind.node.sync_interval!]
}

export function issueStatus(issue: OverviewIssue): IssueStatus {
    if (issue.kind === 'check') {
        return issue.check.last_status === 'errored'
            ? { label: 'Errored', tone: 'danger', tooltip: 'This check could not run on its last attempt.' }
            : { label: 'Failed', tone: 'danger', tooltip: 'This check did not hold on its last run.' }
    }
    if (issue.kind === 'behind') {
        return {
            label: 'Stale',
            tone: 'warning',
            tooltip: `Nothing failed, but this model has gone more than twice its ${cadenceOf(issue)} refresh interval without a run. Its schedule may have stopped.`,
        }
    }
    const problem = issue.attention.problem
    return { label: problem, tone: problem === 'Suspended' ? 'warning' : 'danger', tooltip: PROBLEM_TOOLTIPS[problem] }
}

export function issueDetail(issue: OverviewIssue): string | null {
    if (issue.kind === 'check') {
        return `On ${issue.check.subject_name}`
    }
    if (issue.kind === 'behind') {
        return `Should refresh every ${cadenceOf(issue)}`
    }
    return issue.attention.reason
}

export function downstreamSummary(row: AttentionModel): { holdsUp: string | null; skipped: string | null } {
    return {
        holdsUp: row.downstreamCount > 0 ? `${pluralize(row.downstreamCount, 'model')} downstream` : null,
        skipped: row.skippedCount > 0 ? `${pluralize(row.skippedCount, 'model')} skipped` : null,
    }
}
