import type { ColumnDef } from '@tanstack/react-table'
import { useValues } from 'kea'
import { router } from 'kea-router'

import { Badge, Button, Card, DataTable, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { DashboardV2SummaryApi } from '../generated/api.schemas'
import { DASHBOARD_LIST_LIMIT, dashboardV2ListLogic } from './dashboardV2ListLogic'

const COLUMNS: ColumnDef<DashboardV2SummaryApi>[] = [
    {
        id: 'title',
        header: 'Name',
        accessorKey: 'title',
        minSize: 240,
        meta: { expand: true },
        cell: ({ row }) => (
            <div className="flex min-w-0 flex-col items-start">
                <Button
                    variant="link-foreground"
                    size="sm"
                    nativeButton={false}
                    left
                    render={<LinkPrimitive to={urls.dashboardV2(row.original.uid)} />}
                    className="max-w-full min-w-0"
                    data-attr="dashboard-v2-table-name"
                >
                    <span className="truncate">{row.original.title}</span>
                </Button>
                {row.original.description && (
                    <Text size="xs" variant="muted" className="line-clamp-1 px-2">
                        {row.original.description}
                    </Text>
                )}
            </div>
        ),
    },
    {
        id: 'tags',
        header: 'Tags',
        enableSorting: false,
        cell: ({ row }) => (
            <div className="flex flex-wrap gap-1">
                {row.original.tags.map((tag) => (
                    <Badge key={tag}>{tag}</Badge>
                ))}
            </div>
        ),
    },
    {
        id: 'last_modified_by',
        header: 'Last changed by',
        accessorFn: (row) => row.last_modified_by?.first_name ?? '',
        cell: ({ row }) => (
            <Text size="xs" variant="muted">
                {row.original.last_modified_by?.first_name ?? '–'}
            </Text>
        ),
    },
    {
        id: 'last_modified_at',
        header: 'Last changed',
        accessorKey: 'last_modified_at',
        sortDescFirst: true,
        cell: ({ row }) => (
            <Text size="xs" variant="muted" render={<span />}>
                <TZLabel time={row.original.last_modified_at} />
            </Text>
        ),
    },
]

export function DashboardV2ListTable({ dashboards }: { dashboards: DashboardV2SummaryApi[] }): JSX.Element {
    const { loadedSearch, hasMore } = useValues(dashboardV2ListLogic)

    return (
        <Card size="sm" flush className="pt-0" data-attr="dashboard-v2-table">
            <DataTable
                columns={COLUMNS}
                data={dashboards}
                fullWidth
                size="sm"
                getRowId={(row) => row.id}
                onRowClick={(row) => router.actions.push(urls.dashboardV2(row.uid))}
                empty={
                    <Text size="xs" variant="muted">
                        {loadedSearch ? 'No dashboard matches this search.' : 'No dashboards yet.'}
                    </Text>
                }
            />
            {hasMore && (
                <Text size="xs" variant="muted" className="px-3 py-2">
                    Showing the first {DASHBOARD_LIST_LIMIT} dashboards. Search to find the rest.
                </Text>
            )}
        </Card>
    )
}
