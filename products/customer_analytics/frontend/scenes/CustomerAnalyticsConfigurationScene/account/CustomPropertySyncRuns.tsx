import { IconExternal, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import type { CustomPropertySyncRunApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { runOutcomeNote } from './customPropertyTypes'

const TAG_TYPE_BY_RUN_STATUS: Record<string, LemonTagType> = {
    completed: 'success',
    running: 'primary',
    failed: 'danger',
}

const RUN_STATUS_LABELS: Record<string, string> = {
    completed: 'Completed',
    running: 'Running',
    failed: 'Failed',
}

const RUN_TRIGGERS: Record<string, { label: string; type: LemonTagType }> = {
    scheduled: { label: 'Scheduled', type: 'default' },
    sync: { label: 'Sync now', type: 'option' },
    manual: { label: 'Backfill', type: 'option' },
    backfill: { label: 'Auto backfill', type: 'default' },
}

const ACCOUNT_SEGMENT_LABELS: Record<string, string> = {
    tracked: 'Tracked',
    ignored: 'Ignored',
}

const SYNC_PHASE_LABELS: Record<string, string> = {
    staging: 'Preparing rows',
    dispatching: 'Starting updates',
    syncing: 'Updating accounts',
    completed: 'Completed',
}

type TargetType = 'account' | 'person' | 'group'

type TargetLabels = {
    entity: string
    entityPlural: string
}

const TARGET_LABELS: Record<TargetType, TargetLabels> = {
    account: { entity: 'account', entityPlural: 'accounts' },
    person: { entity: 'person', entityPlural: 'people' },
    group: { entity: 'group', entityPlural: 'groups' },
}

function RunCount({ value }: { value: number }): JSX.Element {
    return <span className={value ? 'font-medium' : 'text-secondary'}>{humanFriendlyNumber(value)}</span>
}

function updatedShare(existing: number, changed: number): string | null {
    if (changed <= 0) {
        return null
    }
    if (existing >= changed) {
        return '100%'
    }
    const share = existing / changed
    if (share < 0.01) {
        return '<1%'
    }
    return percentage(Math.min(share, 0.99), 0)
}

export interface CustomPropertySyncRunsProps {
    runs: CustomPropertySyncRunApi[]
    loading: boolean
    loadFailed: boolean
    targetType: TargetType
    syncsUrl?: string | null
    onReload: () => void
}

export function CustomPropertySyncRuns({
    runs,
    loading,
    loadFailed,
    targetType,
    syncsUrl,
    onReload,
}: CustomPropertySyncRunsProps): JSX.Element {
    const labels = TARGET_LABELS[targetType]
    const accountRuns = targetType === 'account'

    if (loadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: onReload }}>
                Couldn't load run history.
            </LemonBanner>
        )
    }

    const columns: LemonTableColumns<CustomPropertySyncRunApi> = [
        {
            title: 'Status',
            tooltip: accountRuns
                ? 'Whether this account segment finished. A completed run can update zero accounts when no mapped values changed.'
                : 'Whether the run finished. A completed run can update nobody when no mapped values changed.',
            render: (_, run) => {
                const note = runOutcomeNote(run, labels.entityPlural)
                return (
                    <div className="flex items-center gap-2">
                        <Tooltip title={run.error ?? undefined}>
                            <LemonTag
                                type={TAG_TYPE_BY_RUN_STATUS[run.status] ?? 'default'}
                                icon={run.status === 'running' ? <Spinner /> : undefined}
                            >
                                {RUN_STATUS_LABELS[run.status] ?? run.status}
                            </LemonTag>
                        </Tooltip>
                        {note && (
                            <Tooltip title={note.tooltip}>
                                <span className="text-secondary text-xs whitespace-nowrap">{note.label}</span>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
    ]

    if (accountRuns) {
        columns.push(
            {
                title: 'Segment',
                tooltip:
                    'Tracked and ignored accounts run separately. Ignored accounts stay in sync because a property change can make them tracked later.',
                render: (_, run) =>
                    run.account_segment ? (
                        <LemonTag type="muted">
                            {ACCOUNT_SEGMENT_LABELS[run.account_segment] ?? run.account_segment}
                        </LemonTag>
                    ) : (
                        <span className="text-secondary">-</span>
                    ),
            },
            {
                title: 'Phase',
                tooltip: 'Where this account update is in the staging and sync process.',
                render: (_, run) => (
                    <span className="flex items-center gap-2 whitespace-nowrap">
                        <span>{run.sync_phase ? (SYNC_PHASE_LABELS[run.sync_phase] ?? run.sync_phase) : '-'}</span>
                        {(run.attempt ?? 0) > 1 && <LemonTag type="warning">Attempt {run.attempt}</LemonTag>}
                    </span>
                ),
            }
        )
    } else {
        columns.push({
            title: 'Trigger',
            tooltip: 'What started the run: the table schedule, Sync now, or Backfill.',
            render: (_, run) => {
                const trigger = RUN_TRIGGERS[run.trigger]
                return <LemonTag type={trigger?.type ?? 'default'}>{trigger?.label ?? run.trigger}</LemonTag>
            },
        })
    }

    columns.push(
        {
            title: 'Rows read',
            tooltip: accountRuns
                ? 'Rows read from the materialized view snapshot for this account segment.'
                : 'Warehouse rows this sync staged.',
            align: 'right',
            render: (_, run) => <RunCount value={run.rows_read} />,
        },
        {
            title: 'Updated',
            tooltip: `How many ${labels.entityPlural} this run updated, out of the rows whose mapped values changed.`,
            align: 'right',
            render: (_, run) => {
                const share = updatedShare(run.existing, run.changed)
                return (
                    <span className="whitespace-nowrap">
                        <RunCount value={run.existing} />
                        <span className="text-secondary">
                            {' '}
                            of {humanFriendlyNumber(run.changed)} changed{share ? ` (${share})` : ''}
                        </span>
                    </span>
                )
            },
        },
        {
            title: `Skipped (no ${labels.entity})`,
            tooltip: `Changed rows skipped because their key column matched no existing ${labels.entity}.`,
            align: 'right',
            render: (_, run) => (
                <span className="text-secondary">{humanFriendlyNumber(run.skipped_missing_person)}</span>
            ),
        }
    )

    if (accountRuns) {
        columns.push({
            title: 'Run',
            tooltip: 'The materialization job for this update. Share this identifier when asking support for help.',
            render: (_, run) =>
                run.job_id ? (
                    <Tooltip
                        title={
                            <div className="flex flex-col gap-1">
                                <span>Job: {run.job_id}</span>
                                {run.workflow_id && <span>Workflow: {run.workflow_id}</span>}
                            </div>
                        }
                    >
                        <code>{run.job_id.slice(0, 8)}</code>
                    </Tooltip>
                ) : (
                    <span className="text-secondary">-</span>
                ),
        })
    }

    columns.push(
        {
            title: 'Started',
            render: (_, run) =>
                run.started_at ? <TZLabel time={run.started_at} /> : <span className="text-secondary">-</span>,
        },
        {
            title: 'Finished',
            render: (_, run) =>
                run.finished_at ? <TZLabel time={run.finished_at} /> : <span className="text-secondary">-</span>,
        }
    )

    if (syncsUrl) {
        columns.push({
            title: '',
            width: 0,
            render: () => (
                <LemonButton
                    size="small"
                    icon={<IconExternal />}
                    to={syncsUrl}
                    targetBlank
                    tooltip="Open the source's warehouse history"
                />
            ),
        })
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <LemonButton
                    size="small"
                    icon={<IconRefresh />}
                    onClick={onReload}
                    loading={loading}
                    // Pinned because autocapture dashboards and browser tests use this interaction name.
                    data-attr="custom-property-sync-runs-refresh"
                >
                    Refresh
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={runs}
                loading={loading}
                rowKey="id"
                size="small"
                nouns={['run', 'runs']}
                emptyState={
                    accountRuns
                        ? 'No runs yet. Run the source view to start a sync.'
                        : 'No runs yet. Sync or backfill the source to start a run.'
                }
            />
        </div>
    )
}
