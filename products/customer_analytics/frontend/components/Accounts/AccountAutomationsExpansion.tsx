import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { AccountAutomationApi } from '../../generated/api.schemas'
import { accountAutomationsLogic, AUTOMATIONS_PAGE_SIZE } from './accountAutomationsLogic'
import { AccountsEvents } from './constants'

const STATUS_LABELS: Record<string, string> = {
    running: 'In progress',
    queued: 'Queued',
    succeeded: 'Completed',
    success: 'Completed',
    failed: 'Failed',
    canceled: 'Canceled',
}

export function AccountAutomationsExpansion({
    accountId,
    instanceId,
    embedded = true,
}: {
    accountId: string
    instanceId?: string
    embedded?: boolean
}): JSX.Element {
    const logic = accountAutomationsLogic({ accountId, instanceId })
    const { runs, runsLoading, loadFailed, page } = useValues(logic)
    const { loadRuns, setPage } = useActions(logic)

    return (
        <div className="min-w-0">
            {loadFailed ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadRuns() }}>
                    Couldn’t load automations. Try again.
                </LemonBanner>
            ) : !runs && runsLoading ? (
                <LemonSkeleton className="h-40 w-full" />
            ) : !runs ? (
                <LemonSkeleton className="h-40 w-full" />
            ) : (
                <LemonTable<AccountAutomationApi>
                    size="small"
                    embedded={embedded}
                    rowKey={(run) => `${run.workflow_id}:${run.invocation_id}`}
                    dataSource={runs.results}
                    loading={runsLoading}
                    columns={[
                        {
                            title: 'Workflow',
                            key: 'workflow',
                            width: '35%',
                            render: (_, run) => (
                                <div className="flex items-center gap-2 min-w-0">
                                    <Link
                                        to={urls.workflow(run.workflow_id, 'workflow')}
                                        className="max-w-full break-words"
                                        onClick={() => posthog.capture(AccountsEvents.AutomationWorkflowOpened)}
                                    >
                                        {run.workflow_name || 'Untitled workflow'}
                                    </Link>
                                    <LemonTag
                                        className="shrink-0"
                                        type={
                                            run.status === 'failed'
                                                ? 'danger'
                                                : run.status === 'running'
                                                  ? 'primary'
                                                  : 'default'
                                        }
                                    >
                                        {STATUS_LABELS[run.status] ?? run.status}
                                    </LemonTag>
                                </div>
                            ),
                        },
                        {
                            title: 'Triggered at',
                            key: 'triggered_at',
                            render: (_, run) => <TZLabel time={run.triggered_at} />,
                        },
                        {
                            title: 'Last completed step',
                            key: 'last_completed_step_at',
                            render: (_, run) => (
                                <div className="flex flex-col items-start gap-1">
                                    {run.last_completed_step_name && <span>{run.last_completed_step_name}</span>}
                                    {run.last_completed_step_at ? (
                                        <TZLabel time={run.last_completed_step_at} />
                                    ) : (
                                        <span className="text-secondary">Unavailable</span>
                                    )}
                                </div>
                            ),
                        },
                        {
                            title: 'Expected resume at',
                            key: 'expected_resume_at',
                            render: (_, run) =>
                                run.expected_resume_at ? (
                                    <TZLabel time={run.expected_resume_at} />
                                ) : (
                                    <span className="text-secondary">Unavailable</span>
                                ),
                        },
                    ]}
                    emptyState="No retained account automation runs found. Older runs may no longer be available."
                    pagination={{
                        controlled: true,
                        pageSize: AUTOMATIONS_PAGE_SIZE,
                        currentPage: page,
                        useUrl: false,
                        entryCount: runs.count,
                        onForward: () => setPage(page + 1),
                        onBackward: () => setPage(page - 1),
                    }}
                />
            )}
        </div>
    )
}
