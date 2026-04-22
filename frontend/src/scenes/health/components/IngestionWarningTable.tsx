import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber } from 'lib/utils'
import { WARNING_TYPE_TO_DESCRIPTION } from 'scenes/data-management/ingestion-warnings/IngestionWarningsView'

import type { HealthIssue } from '../types'
import { dismissActionColumn, severityColumn } from './healthTableColumns'

function humanizeWarningType(warningType: string): string {
    return warningType
        .split('_')
        .map((word, i) => (i === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word))
        .join(' ')
}

export function IngestionWarningTable({
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
            title: 'Type',
            key: 'warning',
            render: function Render(_, issue: HealthIssue) {
                const warningType = issue.payload.warning_type as string | undefined
                const title = warningType ? humanizeWarningType(warningType) : 'Unknown warning'
                const description = warningType ? WARNING_TYPE_TO_DESCRIPTION[warningType] : null

                return (
                    <div className="py-1">
                        <div className="font-medium">{title}</div>
                        {description && <div className="text-xs text-muted mt-0.5">{description}</div>}
                    </div>
                )
            },
        },
        severityColumn(),
        {
            title: 'Events',
            key: 'affected_count',
            width: 100,
            align: 'right',
            render: function Render(_, issue: HealthIssue) {
                const count = issue.payload.affected_count
                return count != null ? (
                    <span className="font-medium">{humanFriendlyNumber(Number(count))}</span>
                ) : (
                    <span className="text-muted">—</span>
                )
            },
            sorter: (a, b) => (Number(a.payload.affected_count) || 0) - (Number(b.payload.affected_count) || 0),
        },
        {
            title: 'Last seen',
            key: 'last_seen',
            width: 140,
            align: 'right',
            render: function Render(_, issue: HealthIssue) {
                const time = issue.payload.last_seen_at ?? issue.created_at
                return <TZLabel time={time} />
            },
            sorter: (a, b) =>
                new Date(a.payload.last_seen_at ?? a.created_at).getTime() -
                new Date(b.payload.last_seen_at ?? b.created_at).getTime(),
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
                columnKey: 'severity',
                order: -1,
            }}
            noSortingCancellation
            rowClassName="group"
        />
    )
}
