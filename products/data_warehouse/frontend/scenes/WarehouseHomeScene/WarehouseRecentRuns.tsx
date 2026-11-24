import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { Button, DataTable, type DataTableProps, Skeleton, Text } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { PipelineActivityRowApi } from '../../generated/api.schemas'
import { formatCount, formatDuration } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseSectionLink } from '../WarehouseConsole/WarehouseSectionLink'
import { WarehouseStatusBadge } from '../WarehouseConsole/WarehouseStatusBadge'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'
import { warehouseHomeLogic } from './warehouseHomeLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

function runUrl(run: PipelineActivityRowApi): string | null {
    if (run.source_id) {
        return urls.dataWarehouseSource(run.source_id, 'schemas')
    }
    return run.type === 'Materialized view' ? urls.models() : null
}

function runDuration(run: PipelineActivityRowApi): string {
    const end = run.finished_at ? new Date(run.finished_at).getTime() : Date.now()
    return formatDuration(Math.max(0, end - new Date(run.created_at).getTime()))
}

// Declared at module level so TanStack keeps the cell identities across reloads.
const COLUMNS: DataTableProps<PipelineActivityRowApi, unknown>['columns'] = [
    {
        id: 'name',
        header: 'Name',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => {
            const name = row.original.name ?? row.original.type ?? 'Run'
            const to = runUrl(row.original)
            return to ? (
                <LinkPrimitive
                    to={to}
                    className="block max-w-40 truncate"
                    title={name}
                    data-attr="warehouse-home-run"
                    onClick={() => {
                        posthog.capture('warehouse overview link clicked', { target: 'run' })
                    }}
                >
                    {name}
                </LinkPrimitive>
            ) : (
                <span className="block max-w-40 truncate" title={name}>
                    {name}
                </span>
            )
        },
    },
    {
        id: 'type',
        header: 'Type',
        enableSorting: false,
        cell: ({ row }) => (
            <span className="block max-w-32 truncate text-muted-foreground">{row.original.type ?? '-'}</span>
        ),
    },
    {
        id: 'status',
        header: 'Status',
        enableSorting: false,
        cell: ({ row }) => (
            <span title={row.original.status === 'Failed' ? (row.original.latest_error ?? undefined) : undefined}>
                <WarehouseStatusBadge status={row.original.status} />
            </span>
        ),
    },
    {
        id: 'rows',
        header: 'Rows',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => (
            <span className="whitespace-nowrap tabular-nums">
                {row.original.status === 'Running' ? '-' : formatCount(row.original.rows)}
            </span>
        ),
    },
    {
        id: 'duration',
        header: 'Duration',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => <span className="whitespace-nowrap tabular-nums">{runDuration(row.original)}</span>,
    },
    {
        id: 'when',
        header: 'When',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => <WarehouseTime iso={row.original.finished_at ?? row.original.created_at} />,
    },
]

export function WarehouseRecentRuns(): JSX.Element {
    const { recentRuns, recentRunsFailed } = useValues(warehouseHomeLogic)
    const { loadWarehouseHomeRecentRuns } = useActions(warehouseHomeLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const viewAllUrl = featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION] ? urls.etlOverview() : urls.sources()

    let content: JSX.Element
    if (recentRuns === null && !recentRunsFailed) {
        content = <Skeleton className="mx-3 h-24 w-[calc(100%-1.5rem)]" />
    } else if (recentRunsFailed || recentRuns === null) {
        content = (
            <div className="flex flex-wrap items-center gap-2 px-3">
                <Text size="sm" variant="muted">
                    Couldn't load runs.
                </Text>
                <Button onClick={() => loadWarehouseHomeRecentRuns()} data-attr="warehouse-home-runs-retry">
                    Retry
                </Button>
            </div>
        )
    } else if (recentRuns.length === 0) {
        content = (
            <Text size="sm" variant="muted" className="px-3">
                Syncs and view refreshes show up here once they run.
            </Text>
        )
    } else {
        content = <DataTable columns={COLUMNS} data={recentRuns} size="sm" fullWidth getRowId={(run) => run.id} />
    }

    return (
        <WarehouseSection
            title="Recent runs"
            flush={!!recentRuns?.length}
            data-attr="warehouse-home-recent-runs"
            controls={
                <WarehouseSectionLink
                    to={viewAllUrl}
                    data-attr="warehouse-home-runs-view-all"
                    onClick={() => {
                        posthog.capture('warehouse overview link clicked', { target: 'runs' })
                    }}
                >
                    View all
                </WarehouseSectionLink>
            }
        >
            {content}
        </WarehouseSection>
    )
}
