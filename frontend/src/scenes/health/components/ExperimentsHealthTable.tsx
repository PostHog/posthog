import { LemonButton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import type { HealthIssue } from '../types'
import { issueActionsColumn, severityColumn } from './healthTableColumns'

interface ExperimentFix {
    label: string
    to: string
}

// The backend lists the actions in order of preference, so the first one we can link is the fix.
function experimentFix(issue: HealthIssue): ExperimentFix | null {
    const { experiment_id, feature_flag_id, actions } = issue.payload
    if (experiment_id == null) {
        return null
    }
    const firstAction: string | undefined = Array.isArray(actions) ? actions[0] : undefined
    switch (firstAction) {
        case 'open_feature_flag':
            return feature_flag_id == null
                ? null
                : { label: 'Open feature flag', to: urls.featureFlag(feature_flag_id) }
        case 'edit_release_conditions':
            // The flag page locks release conditions for flags linked to an experiment.
            return { label: 'Edit variants', to: urls.experiment(experiment_id, null, { tab: 'variants' }) }
        case 'add_primary_metric':
        case 'add_secondary_metric':
            return { label: 'Add metric', to: urls.experiment(experiment_id) }
        default:
            return { label: 'Open experiment', to: urls.experiment(experiment_id) }
    }
}

function ExperimentIssueDetail({ issue }: { issue: HealthIssue }): JSX.Element {
    const fix = experimentFix(issue)
    return (
        <div className="px-4 py-3">
            <div className="flex flex-col items-start gap-2 p-3 rounded border bg-surface-primary">
                {issue.payload.detail && <p className="m-0 text-secondary">{issue.payload.detail}</p>}
                {fix && (
                    <LemonButton
                        type="primary"
                        size="small"
                        to={fix.to}
                        // pinned: `data-attr` value, so renaming it breaks autocapture insights
                        data-attr={`health-experiments-fix-${issue.payload.actions?.[0] ?? 'open_experiment'}`}
                    >
                        {fix.label}
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

export function ExperimentsHealthTable({
    issues,
    onSnooze,
    onDismiss,
    onUndismiss,
}: {
    issues: HealthIssue[]
    onSnooze: (id: string, duration: string) => void
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}): JSX.Element {
    const columns: LemonTableColumns<HealthIssue> = [
        {
            title: 'Experiment',
            key: 'experiment',
            render: function Render(_, issue: HealthIssue) {
                const { experiment_id, experiment_name, title } = issue.payload
                const name = experiment_name || `Experiment ${experiment_id}`
                return (
                    <div className="py-2">
                        {experiment_id == null ? (
                            <span className="font-semibold">{name}</span>
                        ) : (
                            <Link
                                to={urls.experiment(experiment_id)}
                                className="font-semibold text-link hover:underline"
                            >
                                {name}
                            </Link>
                        )}
                        <div className="mt-0.5">{title}</div>
                    </div>
                )
            },
        },
        severityColumn(),
        {
            title: 'Last seen',
            key: 'last_seen',
            width: 140,
            align: 'right',
            render: function Render(_, issue: HealthIssue) {
                return <TZLabel time={issue.updated_at} />
            },
            sorter: (a, b) => new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime(),
        },
        issueActionsColumn(onSnooze, onDismiss, onUndismiss),
    ]

    return (
        <LemonTable
            dataSource={issues}
            columns={columns}
            rowKey="id"
            embedded
            defaultSorting={{
                columnKey: 'last_seen',
                order: -1,
            }}
            noSortingCancellation
            rowClassName="group"
            expandable={{
                noIndent: true,
                rowExpandable: (issue) => !!issue.payload.detail || experimentFix(issue) !== null,
                expandedRowRender: (issue) => <ExperimentIssueDetail issue={issue} />,
            }}
        />
    )
}
