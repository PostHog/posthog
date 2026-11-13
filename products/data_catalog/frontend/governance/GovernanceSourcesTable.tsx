import { useValues } from 'kea'

import {
    Badge,
    DataTable,
    type DataTableProps,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { usageLogic } from '../usageLogic'
import { SourceRow, agentSurfaceLabel } from '../usageRows'
import { GovernanceColumnHeader } from './GovernanceColumnHeader'
import { GovernanceSectionFailed } from './GovernanceSectionFailed'
import { GovernanceTableEmpty } from './GovernanceTableEmpty'

// The topics and sources tables share a row, so they page alike and keep one height.
const PAGE_SIZE = 5
const SKELETON_ROWS = 4

function UsageCell({ row }: { row: SourceRow }): JSX.Element {
    const label = (
        <Text size="xs" weight="semibold" className="whitespace-nowrap" render={<span />}>
            {pluralize(row.uses, row.kind === 'metric' ? 'run' : 'session')} /{' '}
            {pluralize(row.people, 'person', 'people')}
        </Text>
    )
    if (row.surfaces.length === 0) {
        return label
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" />}>{label}</TooltipTrigger>
            <TooltipContent>
                <div className="flex flex-col gap-1">
                    {row.surfaces.map(([surface, runs]) => (
                        <span key={surface}>
                            {agentSurfaceLabel(surface)}: {humanFriendlyNumber(runs)}
                        </span>
                    ))}
                </div>
            </TooltipContent>
        </Tooltip>
    )
}

const COLUMNS: DataTableProps<SourceRow, unknown>['columns'] = [
    {
        accessorKey: 'name',
        header: 'Source',
        meta: { expand: true },
        enableSorting: false,
        cell: ({ row }) => (
            <div className="flex max-w-96 min-w-32 items-center gap-2">
                <Text size="xs" className="truncate" title={row.original.name} render={<span />}>
                    {row.original.name}
                </Text>
                <Badge>{row.original.kind === 'metric' ? 'Metric' : 'Table'}</Badge>
            </div>
        ),
    },
    {
        id: 'usage',
        accessorFn: (row) => row.people,
        sortingFn: (a, b) => a.original.people - b.original.people || a.original.uses - b.original.uses,
        header: () => (
            <GovernanceColumnHeader
                label="Usage"
                tooltip="Metrics count the runs by agents. Tables count the agent sessions that found a connected source or a view through its description and then queried it. PostHog tables such as events stay out. Both cover the whole scan window. Hover a metric to split its runs by agent."
            />
        ),
        meta: { align: 'right' },
        sortDescFirst: true,
        cell: ({ row }) => <UsageCell row={row.original} />,
    },
]

function SourcesContent(): JSX.Element {
    const { sourceRows, metricsLoadState } = useValues(usageLogic)
    if (metricsLoadState === 'unknown') {
        return (
            <div className="flex flex-col gap-2" aria-busy="true">
                {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                    <Skeleton key={index} className="h-7 w-full" />
                ))}
            </div>
        )
    }
    return (
        <DataTable
            columns={COLUMNS}
            data={sourceRows}
            getRowId={(row) => row.key}
            pageSize={PAGE_SIZE}
            size="sm"
            fullWidth
            empty={
                <GovernanceTableEmpty>
                    No agent ran a catalog metric or found a table by its description in this window.
                </GovernanceTableEmpty>
            }
        />
    )
}

export function GovernanceSourcesTable(): JSX.Element {
    const { failureReasons } = useValues(usageLogic)
    return (
        <section className="flex min-w-0 flex-col gap-2" data-attr="data-catalog-usage-sources">
            <div className="flex min-h-6 items-center">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Top used sources
                </Heading>
            </div>
            {failureReasons.metric_runs && <GovernanceSectionFailed reason={failureReasons.metric_runs} />}
            {failureReasons.table_sources && (
                <Item variant="outline" tone="warning">
                    <ItemContent>
                        <ItemDescription>
                            Table counts are missing, because the table check failed in the last scan.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}
            {!failureReasons.metric_runs && <SourcesContent />}
        </section>
    )
}
