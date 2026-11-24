import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { Button, DataTable, type DataTableProps, Skeleton, Text } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { DataHealthIssueApi } from '../../generated/api.schemas'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseStatusBadge } from '../WarehouseConsole/WarehouseStatusBadge'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'
import { HEALTH_ISSUES_LIMIT, warehouseHomeLogic } from './warehouseHomeLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const TYPE_LABELS: Record<string, string> = {
    external_data_sync: 'Sync',
    source: 'Source',
    materialized_view: 'View',
}

// Declared at module level so TanStack keeps the cell identities across reloads.
const COLUMNS: DataTableProps<DataHealthIssueApi, unknown>['columns'] = [
    {
        accessorKey: 'name',
        header: 'Name',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) =>
            row.original.url ? (
                <LinkPrimitive
                    to={row.original.url}
                    className="block max-w-40 truncate"
                    title={row.original.name}
                    data-attr="warehouse-home-health-issue"
                    onClick={() => {
                        posthog.capture('warehouse overview link clicked', { target: 'issue' })
                    }}
                >
                    {row.original.name}
                </LinkPrimitive>
            ) : (
                <span className="block max-w-40 truncate" title={row.original.name}>
                    {row.original.name}
                </span>
            ),
    },
    {
        id: 'type',
        header: 'Type',
        enableSorting: false,
        cell: ({ row }) => {
            const typeLabel = TYPE_LABELS[row.original.type] ?? row.original.type
            const text = row.original.source_type ? `${typeLabel} · ${row.original.source_type}` : typeLabel
            return <span className="block max-w-32 truncate text-muted-foreground">{text}</span>
        },
    },
    {
        accessorKey: 'status',
        header: 'Status',
        enableSorting: false,
        cell: ({ row }) => <WarehouseStatusBadge status={row.original.status} />,
    },
    {
        accessorKey: 'error',
        header: 'Error',
        enableSorting: false,
        cell: ({ row }) => (
            <span
                className="block max-w-56 truncate text-xs text-muted-foreground"
                title={row.original.error ?? undefined}
            >
                {row.original.error ?? '-'}
            </span>
        ),
    },
    {
        accessorKey: 'failed_at',
        header: 'Failed',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => (row.original.failed_at ? <WarehouseTime iso={row.original.failed_at} /> : '-'),
    },
]

export function WarehouseHealth(): JSX.Element {
    const { warehouseIssues, healthIssuesFailed } = useValues(warehouseHomeLogic)
    const { loadWarehouseHomeHealthIssues } = useActions(warehouseHomeLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const viewAllUrl = featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION] ? urls.etlOverview() : urls.sources()

    let content: JSX.Element
    if (warehouseIssues === null && !healthIssuesFailed) {
        content = <Skeleton className="mx-3 h-24 w-[calc(100%-1.5rem)]" />
    } else if (healthIssuesFailed || warehouseIssues === null) {
        content = (
            <div className="flex flex-wrap items-center gap-2 px-3">
                <Text size="sm" variant="muted">
                    Couldn't load health issues.
                </Text>
                <Button onClick={() => loadWarehouseHomeHealthIssues()} data-attr="warehouse-home-health-retry">
                    Retry
                </Button>
            </div>
        )
    } else if (warehouseIssues.length === 0) {
        content = (
            <Text size="sm" variant="muted" className="px-3">
                Everything is healthy
            </Text>
        )
    } else {
        content = (
            <>
                <DataTable
                    columns={COLUMNS}
                    data={warehouseIssues.slice(0, HEALTH_ISSUES_LIMIT)}
                    size="sm"
                    fullWidth
                    getRowId={(issue) => `${issue.type}-${issue.id}`}
                />
                {warehouseIssues.length > HEALTH_ISSUES_LIMIT && (
                    <div className="flex flex-wrap items-center justify-between gap-2 px-3 pt-2">
                        <Text size="xs" variant="muted">
                            {`Showing ${HEALTH_ISSUES_LIMIT} of ${warehouseIssues.length}`}
                        </Text>
                        <Button
                            variant="link"
                            size="sm"
                            nativeButton={false}
                            render={<LinkPrimitive to={viewAllUrl} />}
                            data-attr="warehouse-home-health-view-all"
                            onClick={() => {
                                posthog.capture('warehouse overview link clicked', { target: 'issues' })
                            }}
                        >
                            {`View all ${warehouseIssues.length} issues`}
                        </Button>
                    </div>
                )}
            </>
        )
    }

    return (
        <WarehouseSection title="Needs attention" flush={!!warehouseIssues?.length} data-attr="warehouse-home-health">
            {content}
        </WarehouseSection>
    )
}
