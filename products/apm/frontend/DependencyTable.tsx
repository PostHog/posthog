import { LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { DEPENDENCY_KIND_LABEL, errorRateOf } from './dependencies'
import type { DependencyEdgeApi } from './generated/api.schemas'
import { formatMs, formatPercent } from './healthDisplay'

interface DependencyTableProps {
    title: string
    edges: DependencyEdgeApi[]
    loading: boolean
    emptyState: string
    dataAttr: string
    serviceLink: (service: string) => { to: string } | { onClick: () => void }
}

export function DependencyTable({
    title,
    edges,
    loading,
    emptyState,
    dataAttr,
    serviceLink,
}: DependencyTableProps): JSX.Element {
    const columns: LemonTableColumns<DependencyEdgeApi> = [
        {
            title: 'Caller',
            key: 'caller',
            render: (_, edge) => (
                <Link {...serviceLink(edge.caller)} data-attr="apm-dependency-caller">
                    {edge.caller}
                </Link>
            ),
        },
        {
            title: 'Callee',
            key: 'callee',
            render: (_, edge) => (
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    {edge.inferred ? (
                        <span className="font-semibold">{edge.callee}</span>
                    ) : (
                        <Link {...serviceLink(edge.callee)} data-attr="apm-dependency-callee">
                            {edge.callee}
                        </Link>
                    )}
                    <LemonTag type={edge.inferred ? 'muted' : 'default'} size="small">
                        {edge.inferred
                            ? `${DEPENDENCY_KIND_LABEL[edge.kind]}, inferred`
                            : DEPENDENCY_KIND_LABEL[edge.kind]}
                    </LemonTag>
                </span>
            ),
        },
        {
            title: 'Requests',
            key: 'requests',
            align: 'right',
            sorter: (a, b) => a.requests - b.requests,
            render: (_, edge) => <span className="font-mono">{edge.requests.toLocaleString()}</span>,
        },
        {
            title: 'Errors',
            key: 'error_rate',
            align: 'right',
            sorter: (a, b) => errorRateOf(a) - errorRateOf(b),
            render: (_, edge) => <span className="font-mono">{formatPercent(errorRateOf(edge))}</span>,
        },
        {
            title: 'p95',
            key: 'p95_ms',
            align: 'right',
            sorter: (a, b) => (a.p95_ms ?? 0) - (b.p95_ms ?? 0),
            render: (_, edge) => <span className="font-mono">{formatMs(edge.p95_ms)}</span>,
        },
    ]

    return (
        // min-w-0 lets a grid cell shrink below the table's width so LemonTable scrolls instead of clipping.
        <div className="flex flex-col gap-1 min-w-0">
            <h3 className="mb-0 text-sm font-semibold">{title}</h3>
            <LemonTable
                columns={columns}
                dataSource={edges}
                rowKey={(edge) => `${edge.caller}->${edge.callee}`}
                loading={loading}
                emptyState={emptyState}
                size="small"
                data-attr={dataAttr}
            />
        </div>
    )
}
