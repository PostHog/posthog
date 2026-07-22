import { useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { cohortsStaffToolsLogic, StaffCohort } from './cohortsStaffToolsLogic'

function recalculateDisabledReason(cohort: StaffCohort): string | undefined {
    if (cohort.deleted) {
        return 'This cohort is deleted'
    }
    if (cohort.is_static) {
        return 'Static cohorts are populated from their source and cannot be recalculated'
    }
    return undefined
}

export function StaffCohortsTable({
    cohorts,
    loading,
    emptyState,
    onRecalculate,
}: {
    cohorts: StaffCohort[]
    loading: boolean
    emptyState: string
    onRecalculate: (cohortId: number) => void
}): JSX.Element {
    const { pendingRecalculateCohortIds, recalculateResultLoading } = useValues(cohortsStaffToolsLogic)

    const columns: LemonTableColumns<StaffCohort> = [
        {
            title: 'Cohort',
            key: 'cohort',
            render: (_, cohort) => (
                <span>
                    <Link to={urls.project(cohort.project_id, urls.cohort(cohort.id))}>
                        {cohort.name || 'Untitled'}
                    </Link>{' '}
                    <span className="text-secondary">(#{cohort.id})</span>
                </span>
            ),
        },
        {
            title: 'Team',
            key: 'team',
            render: (_, cohort) => (
                <span>
                    {cohort.team_name} <span className="text-secondary">(#{cohort.team_id})</span>
                </span>
            ),
        },
        {
            title: 'State',
            key: 'state',
            render: (_, cohort) => (
                <span className="flex flex-wrap gap-1">
                    {cohort.deleted && <LemonTag type="danger">Deleted</LemonTag>}
                    {cohort.is_static && <LemonTag type="muted">Static</LemonTag>}
                    {cohort.is_calculating && <LemonTag type="completion">Calculating</LemonTag>}
                    {!cohort.deleted && !cohort.is_static && !cohort.is_calculating && (
                        <LemonTag type="success">Idle</LemonTag>
                    )}
                </span>
            ),
        },
        {
            title: 'Version',
            key: 'version',
            tooltip: 'Completed version → requested version. A lasting mismatch means a calculation is stuck.',
            render: (_, cohort) =>
                cohort.pending_version !== null && cohort.pending_version !== cohort.version ? (
                    <span className="text-warning font-semibold">
                        {cohort.version ?? '–'} → {cohort.pending_version}
                    </span>
                ) : (
                    <span>{cohort.version ?? '–'}</span>
                ),
        },
        {
            title: 'Last calculation',
            key: 'last_calculation',
            render: (_, cohort) =>
                cohort.last_calculation ? (
                    <TZLabel time={cohort.last_calculation} />
                ) : (
                    <span className="text-secondary">Never</span>
                ),
        },
        {
            title: 'Errors',
            key: 'errors',
            render: (_, cohort) =>
                cohort.errors_calculating > 0 ? (
                    <span className="flex items-baseline gap-1 text-danger">
                        {cohort.errors_calculating}
                        {cohort.last_error_at && (
                            <span className="flex items-baseline gap-1 text-secondary">
                                (last <TZLabel time={cohort.last_error_at} />)
                            </span>
                        )}
                    </span>
                ) : (
                    <span className="text-secondary">0</span>
                ),
        },
        {
            title: 'Count',
            key: 'count',
            render: (_, cohort) => cohort.count?.toLocaleString() ?? <span className="text-secondary">–</span>,
        },
        {
            key: 'actions',
            width: 0,
            render: (_, cohort) => {
                const pending = pendingRecalculateCohortIds.includes(cohort.id)
                return (
                    <LemonButton
                        type="secondary"
                        size="small"
                        loading={pending}
                        disabledReason={
                            recalculateDisabledReason(cohort) ??
                            (recalculateResultLoading && !pending
                                ? 'Another recalculation is being enqueued'
                                : undefined)
                        }
                        onClick={() =>
                            LemonDialog.open({
                                title: `Force recalculation of cohort ${cohort.id}?`,
                                description:
                                    "This bumps the cohort's pending version and enqueues a full recalculation, " +
                                    'including any cohorts it depends on or that depend on it. Any stale in-flight ' +
                                    'calculation is superseded.',
                                primaryButton: {
                                    children: 'Force recalculate',
                                    onClick: () => onRecalculate(cohort.id),
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                },
                            })
                        }
                        data-attr="cohorts-staff-recalculate"
                    >
                        Force recalculate
                    </LemonButton>
                )
            },
        },
    ]

    return (
        <LemonTable
            dataSource={cohorts}
            columns={columns}
            loading={loading}
            rowKey={(cohort) => cohort.id}
            emptyState={emptyState}
        />
    )
}
