import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import {
    Button,
    DataTable,
    type DataTableProps,
    Heading,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { Language } from 'lib/components/CodeSnippet'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { newMetricUrl } from '../common'
import { QuillMetricCodeBlock } from '../components/QuillMetricCodeBlock'
import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { ProposedRow, proposedRowPrefill } from '../proposedRows'
import { usageLogic } from '../usageLogic'
import { GovernanceColumnHeader } from './GovernanceColumnHeader'
import { GovernanceSectionFailed } from './GovernanceSectionFailed'
import { GovernanceTableEmpty } from './GovernanceTableEmpty'
import { QuillProposedMetricSources } from './QuillProposedMetricSources'

const PAGE_SIZE = 10
const COMPLEXITY_LABELS: Record<number, string> = { 0: 'Unknown', 1: 'Low', 2: 'Medium', 3: 'High' }

function DerivedFrom({ metric }: { metric: DataCatalogMetricApi | undefined }): JSX.Element {
    if (!metric) {
        return (
            <Text size="xs" variant="muted">
                Derived from a catalog metric
            </Text>
        )
    }
    return (
        <Text size="xs" variant="muted" className="flex flex-wrap items-center gap-x-1">
            Derived from
            <Button
                variant="link-muted"
                size="inline"
                nativeButton={false}
                render={<LinkPrimitive to={urls.dataCatalogMetric(metric.name)} />}
                data-attr="data-catalog-usage-derived-from-link"
            >
                {metric.display_name || metric.name}
            </Button>
        </Text>
    )
}

function ProposedMetricName({ row, expanded }: { row: ProposedRow; expanded: boolean }): JSX.Element {
    const { metricsById } = useValues(usageLogic)
    return (
        <div className="flex max-w-xl min-w-40 flex-col items-start gap-0.5 py-1">
            <Button
                variant="link-foreground"
                size="inline"
                nativeButton={false}
                render={<LinkPrimitive to={newMetricUrl(proposedRowPrefill(row))} />}
                className={row.name ? 'font-semibold' : 'font-mono'}
                data-attr="data-catalog-usage-proposed-metric-link"
            >
                <span className={row.name ? 'truncate' : 'line-clamp-2 text-start whitespace-normal'}>
                    {row.name ?? row.measure}
                </span>
            </Button>
            {row.description && (
                <Tooltip>
                    <TooltipTrigger render={<span className="block max-w-full" />}>
                        <Text size="xs" variant="muted" className="block truncate" render={<span />}>
                            {row.description}
                        </Text>
                    </TooltipTrigger>
                    <TooltipContent>{row.description}</TooltipContent>
                </Tooltip>
            )}
            {row.outcome === 'slice' && <DerivedFrom metric={metricsById[row.matchedMetricId ?? '']} />}
            {expanded && (
                // Zero width keeps the SQL out of the column's natural width, so a long query wraps inside the cell.
                <div className="mt-2 flex w-0 min-w-full flex-col gap-2">
                    {row.measures > 1 && <Text size="xs">This proposal merges {row.measures} recurring measures.</Text>}
                    <QuillMetricCodeBlock code={row.sql} language={Language.SQL} wrap />
                </div>
            )}
        </div>
    )
}

function proposedColumns(expandedKeys: Set<string>): DataTableProps<ProposedRow, unknown>['columns'] {
    return [
        {
            id: 'expand',
            header: '',
            enableSorting: false,
            cell: ({ row }) => (
                <IconChevronRight
                    aria-hidden
                    className={cn(
                        'mt-2 size-3 text-muted-foreground motion-safe:transition-transform',
                        expandedKeys.has(row.original.key) && 'rotate-90'
                    )}
                />
            ),
        },
        {
            accessorKey: 'name',
            header: 'Proposed metric',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) => <ProposedMetricName row={row.original} expanded={expandedKeys.has(row.original.key)} />,
        },
        {
            id: 'sources',
            header: () => (
                <GovernanceColumnHeader
                    label="Where it is used"
                    tooltip="Where people wrote the query and where they saw it."
                />
            ),
            cell: ({ row }) => (
                <div className="min-w-64">
                    <QuillProposedMetricSources metric={row.original} />
                </div>
            ),
        },
        {
            accessorKey: 'complexity',
            header: () => (
                <GovernanceColumnHeader
                    label="Complexity"
                    tooltip="How hard the query is to write by hand. Joins, subqueries, window functions, conditional aggregates and calculations raise it. Complex queries come first, because they most need one shared definition."
                />
            ),
            sortDescFirst: true,
            cell: ({ row }) => COMPLEXITY_LABELS[row.original.complexity] ?? COMPLEXITY_LABELS[0],
        },
        {
            accessorKey: 'people',
            header: () => (
                <GovernanceColumnHeader
                    label="People"
                    tooltip="People who wrote the query or created a chart of it, directly or through an agent."
                />
            ),
            meta: { align: 'right' },
            sortDescFirst: true,
        },
        {
            accessorKey: 'built',
            header: () => (
                <GovernanceColumnHeader
                    label="Built"
                    tooltip="Each time a person or an agent wrote the query, plus one for each saved chart and each query in a notebook or canvas."
                />
            ),
            meta: { align: 'right' },
            sortDescFirst: true,
        },
        {
            accessorKey: 'viewed',
            header: () => (
                <GovernanceColumnHeader
                    label="Viewed"
                    tooltip="Runs that a person saw, in the web app or an agent session. Whoever builds a query also sees it."
                />
            ),
            meta: { align: 'right' },
            sortDescFirst: true,
        },
    ]
}

export function GovernanceProposedTable(): JSX.Element {
    const { proposedRows, failureReasons } = useValues(usageLogic)
    const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set())

    const toggle = (row: ProposedRow): void => {
        setExpandedKeys((current) => {
            const next = new Set(current)
            if (next.has(row.key)) {
                next.delete(row.key)
            } else {
                next.add(row.key)
            }
            return next
        })
    }

    return (
        <section className="flex min-w-0 flex-col gap-2" data-attr="data-catalog-usage-proposed">
            <Heading size="sm" render={<h3 className="m-0" />}>
                Proposed metrics
            </Heading>
            {failureReasons.uncovered ? (
                <GovernanceSectionFailed reason={failureReasons.uncovered} />
            ) : (
                <DataTable
                    columns={proposedColumns(expandedKeys)}
                    data={proposedRows}
                    getRowId={(row) => row.key}
                    pageSize={PAGE_SIZE}
                    size="sm"
                    fullWidth
                    onRowClick={toggle}
                    empty={
                        <GovernanceTableEmpty>
                            No measure needs a metric yet. One appears here once several people compute the same
                            measure.
                        </GovernanceTableEmpty>
                    }
                />
            )}
        </section>
    )
}
