import { LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { formatChange } from './deploymentsDisplay'
import type { DeploymentVersionApi } from './generated/api.schemas'
import { formatMs, formatPercent } from './healthDisplay'

export interface DeploymentVersionsTableProps {
    versions: DeploymentVersionApi[]
    loading: boolean
    emptyState: React.ReactNode
    dataAttr: string
}

export function DeploymentVersionsTable({
    versions,
    loading,
    emptyState,
    dataAttr,
}: DeploymentVersionsTableProps): JSX.Element {
    const columns: LemonTableColumns<DeploymentVersionApi> = [
        {
            title: 'Version',
            key: 'version',
            render: (_, row) => (
                <span className="flex items-center gap-2">
                    <span className="font-mono font-semibold">{row.version}</span>
                    {row.active && (
                        <LemonTag type="success" size="small">
                            Active
                        </LemonTag>
                    )}
                </span>
            ),
        },
        {
            title: 'First seen',
            key: 'first_seen',
            render: (_, row) => <TZLabel time={row.first_seen} />,
        },
        {
            title: 'Last seen',
            key: 'last_seen',
            render: (_, row) => <TZLabel time={row.last_seen} />,
        },
        {
            title: 'Requests',
            key: 'requests',
            align: 'right',
            render: (_, row) => <span className="font-mono">{row.requests.toLocaleString()}</span>,
        },
        {
            title: 'Error rate',
            key: 'error_rate',
            align: 'right',
            render: (_, row) => (
                <span className="font-mono">
                    {formatPercent(row.error_rate)}
                    <ChangeNote text={formatChange('error', row)} bad={(row.error_rate_change ?? 0) > 0} />
                </span>
            ),
        },
        {
            title: 'p95',
            key: 'p95_ms',
            align: 'right',
            render: (_, row) => (
                <span className="font-mono">
                    {formatMs(row.p95_ms)}
                    <ChangeNote text={formatChange('p95', row)} bad={(row.p95_change_pct ?? 0) > 0} />
                </span>
            ),
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={versions}
            rowKey="version"
            loading={loading}
            emptyState={emptyState}
            data-attr={dataAttr}
        />
    )
}

function ChangeNote({ text, bad }: { text: string | null; bad: boolean }): JSX.Element | null {
    return text ? <span className={`ml-2 text-xs ${bad ? 'text-danger' : 'text-success'}`}>{text}</span> : null
}
