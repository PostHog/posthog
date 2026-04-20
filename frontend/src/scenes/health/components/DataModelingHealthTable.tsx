import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type { HealthIssue } from '../types'
import { getErrorLabelForMaterializedView } from '../utils/materializedViewErrors'
import { dismissActionColumn, severityColumn } from './healthTableColumns'

export function DataModelingHealthTable({
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
            title: 'View',
            key: 'view',
            render: function Render(_, issue: HealthIssue) {
                const { pipeline_name } = issue.payload
                return <span className="font-medium">{pipeline_name ?? 'Unknown view'}</span>
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
                const errorHelp = getErrorLabelForMaterializedView(error)
                return (
                    <div className="py-1">
                        <div className="text-xs text-secondary whitespace-pre-wrap break-words">{error}</div>
                        {errorHelp && <div className="text-xs text-muted mt-1">{errorHelp}</div>}
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
