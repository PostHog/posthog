import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type { HealthIssue } from '../types'
import { dismissActionColumn, severityColumn } from './healthTableColumns'

export function PipelineHealthTable({
    issues,
    onDismiss,
    onUndismiss,
}: {
    issues: HealthIssue[]
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}): JSX.Element {
    const columns: LemonTableColumns<HealthIssue> = [
        {
            title: 'Pipeline',
            key: 'pipeline',
            render: function Render(_, issue: HealthIssue) {
                const { pipeline_name, source_type } = issue.payload
                return (
                    <div className="py-1">
                        <div className="font-medium">{pipeline_name ?? 'Unknown pipeline'}</div>
                        {source_type && source_type !== 'unknown' && (
                            <div className="text-xs text-muted mt-0.5">{source_type}</div>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Error',
            key: 'error',
            render: function Render(_, issue: HealthIssue) {
                const { error } = issue.payload
                if (!error) {
                    return <span className="text-muted">—</span>
                }
                return <div className="text-xs text-secondary whitespace-pre-wrap break-words">{error}</div>
            },
        },
        severityColumn(),
        {
            title: 'Last seen',
            key: 'last_seen',
            width: 140,
            align: 'right',
            render: function Render(_, issue: HealthIssue) {
                return <TZLabel time={issue.created_at} />
            },
            sorter: (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
        },
        dismissActionColumn(onDismiss, onUndismiss),
    ]

    return (
        <LemonTable
            dataSource={issues}
            columns={columns}
            embedded
            size="small"
            defaultSorting={{
                columnKey: 'last_seen',
                order: -1,
            }}
            noSortingCancellation
            rowClassName="group"
        />
    )
}
