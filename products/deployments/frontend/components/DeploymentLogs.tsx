import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { deploymentLogic } from '../deploymentLogic'
import type { DeploymentLogEntryApi } from '../generated/api.schemas'

const LEVEL_TAG: Record<string, LemonTagType> = {
    info: 'default',
    warn: 'warning',
    warning: 'warning',
    error: 'danger',
}

interface DeploymentLogsProps {
    projectId: string
    id: string
}

export function DeploymentLogs({ projectId, id }: DeploymentLogsProps): JSX.Element {
    const { deploymentLogs, deploymentLogsLoading } = useValues(deploymentLogic({ projectId, id }))
    const { refreshDeploymentLogs } = useActions(deploymentLogic({ projectId, id }))

    const rows = deploymentLogs?.results ?? []
    const hasMore = deploymentLogs?.has_more ?? false
    const rowLimit = deploymentLogs?.row_limit ?? null

    const columns: LemonTableColumns<DeploymentLogEntryApi> = [
        {
            title: 'Time',
            dataIndex: 'timestamp',
            width: 0,
            render: (_, row) => (row.timestamp ? <TZLabel time={row.timestamp} /> : <span>—</span>),
        },
        {
            title: 'Level',
            dataIndex: 'level',
            width: 0,
            render: (_, row) =>
                row.level ? (
                    <LemonTag type={LEVEL_TAG[row.level.toLowerCase()] ?? 'default'}>{row.level}</LemonTag>
                ) : (
                    <span className="text-secondary">—</span>
                ),
        },
        {
            title: 'Step',
            dataIndex: 'step',
            width: 0,
            render: (_, row) =>
                row.step ? <LemonTag type="default">{row.step}</LemonTag> : <span className="text-secondary">—</span>,
        },
        {
            title: 'Line',
            dataIndex: 'line',
            render: (_, row) => (
                <span className="font-mono text-xs whitespace-pre-wrap break-all">{row.line ?? ''}</span>
            ),
        },
        {
            title: 'Exit',
            dataIndex: 'exit_code',
            width: 0,
            render: (_, row) =>
                row.exit_code === null || row.exit_code === undefined ? null : (
                    <LemonTag type={row.exit_code === 0 ? 'success' : 'danger'}>{row.exit_code}</LemonTag>
                ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <div>
                    <h3 className="text-lg font-semibold mb-0">Logs</h3>
                    <p className="text-secondary text-sm mb-0">
                        Build output emitted by this deployment's pipeline, oldest first.
                    </p>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    onClick={() => refreshDeploymentLogs()}
                    loading={deploymentLogsLoading}
                >
                    Refresh
                </LemonButton>
            </div>

            {hasMore && rowLimit !== null && (
                <LemonBanner type="info">Showing the most recent {rowLimit} lines — older lines exist.</LemonBanner>
            )}

            <LemonTable
                dataSource={rows}
                columns={columns}
                loading={deploymentLogsLoading && rows.length === 0}
                rowKey={(row, index) => `${row.timestamp}-${index}`}
                emptyState="No build logs yet — the build hasn't emitted any $log events with this deployment id set."
                data-attr="deployment-logs-table"
            />
        </div>
    )
}
