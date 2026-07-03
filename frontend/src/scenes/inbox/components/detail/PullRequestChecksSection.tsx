import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonSkeleton, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { CheckRunResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { DetailSection } from './DetailSection'

// A check run's display state: while it hasn't completed, its lifecycle status ('queued' /
// 'in_progress') is what matters; once completed, its conclusion is. Falls back to 'pending' so an
// unknown/absent status still reads as in-flight rather than silently green.
function checkRunState(run: CheckRunResponseApi): string {
    if (run.status && run.status !== 'completed') {
        return run.status
    }
    return run.conclusion || 'pending'
}

const FAILING_STATES = new Set(['failure', 'timed_out', 'cancelled', 'action_required', 'startup_failure', 'stale'])
const PENDING_STATES = new Set(['pending', 'queued', 'in_progress'])

// success → green, failures → red, still-running → amber, everything else (neutral / skipped) → muted.
function stateTagType(state: string): LemonTagType {
    if (state === 'success') {
        return 'success'
    }
    if (FAILING_STATES.has(state)) {
        return 'danger'
    }
    if (PENDING_STATES.has(state)) {
        return 'warning'
    }
    return 'muted'
}

// The rollup summarizes all checks into one green/red/pending tag mirroring GitHub's merge-box state.
const ROLLUP_TAG_TYPE: Record<string, LemonTagType> = {
    success: 'success',
    failure: 'danger',
    pending: 'warning',
}
const ROLLUP_LABEL: Record<string, string> = {
    success: 'All checks passed',
    failure: 'Some checks failed',
    pending: 'Checks running',
}

/**
 * "Checks" section: the report's latest `commit` artefact's CI check runs plus a green/red rollup,
 * so the PR's CI state is visible in-app without opening GitHub. The data is loaded by
 * `inboxReportDetailLogic` (keyed to the report, cascading off the artefact load) — this component
 * just renders the current state. Mirrors `PullRequestDiffPanel`.
 */
export function PullRequestChecksSection({ report }: { report: SignalReport }): JSX.Element {
    const { reportChecks, reportChecksError } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const rollup = reportChecks?.rollup ?? null
    const checkRuns = reportChecks?.check_runs ?? []

    return (
        <DetailSection
            icon={<IconCheckCircle />}
            title="Checks"
            afterTitle={
                rollup ? (
                    <LemonTag type={ROLLUP_TAG_TYPE[rollup] ?? 'muted'}>{ROLLUP_LABEL[rollup] ?? rollup}</LemonTag>
                ) : undefined
            }
        >
            {reportChecksError ? (
                <p className="m-0 py-4 text-sm text-danger">{reportChecksError}</p>
            ) : !reportChecks ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-6 w-full" />
                    <LemonSkeleton className="h-6 w-3/4" />
                </div>
            ) : checkRuns.length === 0 ? (
                <p className="m-0 py-2 text-sm text-tertiary">No checks reported</p>
            ) : (
                <div className="flex flex-col divide-y divide-border">
                    {checkRuns.map((run, i) => {
                        const state = checkRunState(run)
                        return (
                            <div
                                key={`${run.name}-${i}`}
                                className="flex items-center justify-between gap-2 py-1.5 min-w-0"
                            >
                                {run.html_url ? (
                                    <Link to={run.html_url} target="_blank" className="truncate text-sm text-primary">
                                        {run.name || 'Unnamed check'}
                                    </Link>
                                ) : (
                                    <span className="truncate text-sm text-primary">{run.name || 'Unnamed check'}</span>
                                )}
                                <LemonTag type={stateTagType(state)} className="shrink-0">
                                    {state.replace(/_/g, ' ')}
                                </LemonTag>
                            </div>
                        )
                    })}
                </div>
            )}
        </DetailSection>
    )
}
