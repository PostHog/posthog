import { useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Button, DataTable, type DataTableProps, Text, cn } from '@posthog/quill'

import { Language } from 'lib/components/CodeSnippet'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { CATALOG_LAYER_PAGE_SIZE } from '../catalogPagination'
import { newMetricUrl } from '../common'
import { QuillMetricCodeBlock } from '../components/QuillMetricCodeBlock'
import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { GovernanceColumnHeader } from '../governance/GovernanceColumnHeader'
import { ProposedRow, complexityLabel, proposedRowPrefill } from '../proposedRows'
import { hasSources, proposedUsageSummary, proposedUsageTotals } from '../proposedSources'
import { usageLogic } from '../usageLogic'
import { catalogSuggestedMetricsLogic } from './catalogSuggestedMetricsLogic'
import { QuillProposedMetricSources } from './QuillProposedMetricSources'

function DerivedFrom({
    metric,
    className,
}: {
    metric: DataCatalogMetricApi | undefined
    className?: string
}): JSX.Element {
    if (!metric) {
        return (
            <Text size="xs" variant="muted" className="truncate" render={<span />}>
                Derived from a catalog metric
            </Text>
        )
    }
    return (
        <Text
            size="xs"
            variant="muted"
            className={cn('flex min-w-0 items-center gap-x-1', className)}
            render={<span />}
        >
            <span className="shrink-0">Derived from</span>
            <Button
                variant="link-muted"
                size="inline"
                nativeButton={false}
                render={<LinkPrimitive to={urls.dataCatalogMetric(metric.name)} />}
                className="max-w-full min-w-0 shrink"
                data-attr="data-catalog-governance-derived-from-link"
            >
                <span className="truncate">{metric.display_name || metric.name}</span>
            </Button>
        </Text>
    )
}

function ProposedMetricName({ row, expanded }: { row: ProposedRow; expanded: boolean }): JSX.Element {
    const { metricsById } = useValues(usageLogic)
    const isSlice = row.outcome === 'slice'
    const matchedMetric = metricsById[row.matchedMetricId ?? '']
    return (
        // Zero width keeps the name, the description and the SQL out of the column's natural width. The column then
        // takes the space that the other columns leave, and long text wraps or truncates inside it.
        <div className="flex min-w-40 flex-col items-start gap-0.5 py-1">
            <div className="flex w-0 min-w-full">
                <Button
                    variant="link-foreground"
                    size="inline"
                    nativeButton={false}
                    render={<LinkPrimitive to={newMetricUrl(proposedRowPrefill(row))} />}
                    className={cn('max-w-full', row.name ? 'font-semibold' : 'font-mono')}
                    data-attr="data-catalog-governance-proposed-metric-link"
                >
                    <span className={expanded ? 'text-start break-words whitespace-normal' : 'truncate'}>
                        {row.name ?? row.measure}
                    </span>
                </Button>
            </div>
            {expanded ? (
                // The ignore attribute lets a person select text without collapsing the row.
                <div className="flex w-0 min-w-full flex-col gap-2" data-row-click-ignore>
                    {(isSlice || row.description) && (
                        <div className="flex flex-col gap-0.5">
                            {isSlice && <DerivedFrom metric={matchedMetric} className="flex-wrap" />}
                            {row.description && (
                                <Text size="xs" variant="muted" className="m-0 whitespace-normal" render={<p />}>
                                    {row.description}
                                </Text>
                            )}
                        </div>
                    )}
                    {row.measures > 1 && (
                        <Text size="xs">This suggestion merges {row.measures} recurring measures.</Text>
                    )}
                    <QuillMetricCodeBlock code={row.sql} language={Language.SQL} wrap />
                </div>
            ) : (
                // Every collapsed row renders this line, empty or not, so all collapsed rows have one height.
                <div className="flex min-h-4 w-0 min-w-full items-center gap-1">
                    {isSlice && <DerivedFrom metric={matchedMetric} />}
                    {row.description && (
                        <Text size="xs" variant="muted" className="truncate" render={<span />}>
                            {row.description}
                        </Text>
                    )}
                </div>
            )}
        </div>
    )
}

function ProposedMetricUsage({ row, expanded }: { row: ProposedRow; expanded: boolean }): JSX.Element {
    return (
        <div className="flex w-48 flex-col items-start py-1 @3xl:w-80 @5xl:w-md">
            <Text size="sm" className={cn('block max-w-full', !expanded && 'truncate')} render={<span />}>
                {proposedUsageSummary(row)}
            </Text>
            {expanded && (
                <div className="flex flex-col gap-1" data-row-click-ignore>
                    {hasSources(row) && <QuillProposedMetricSources metric={row} />}
                    <Text size="xs" variant="muted" className="m-0" render={<p />}>
                        {proposedUsageTotals(row)}
                    </Text>
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
            header: 'Suggested metric',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) => <ProposedMetricName row={row.original} expanded={expandedKeys.has(row.original.key)} />,
        },
        {
            id: 'usage',
            accessorKey: 'people',
            header: () => (
                <GovernanceColumnHeader
                    label="Where it is used"
                    tooltip="How many people wrote or charted the query, and the dashboards, charts, agent sessions and pages where it appears. Open a row to see each one. Sorting orders the rows by the number of people."
                />
            ),
            sortDescFirst: true,
            cell: ({ row }) => <ProposedMetricUsage row={row.original} expanded={expandedKeys.has(row.original.key)} />,
        },
        {
            accessorKey: 'complexity',
            header: () => (
                <GovernanceColumnHeader
                    label="Query complexity"
                    tooltip="How hard the query is to write by hand. Joins, subqueries, window functions, conditional aggregates and calculations raise it. Complex queries come first, because they most need one shared definition."
                />
            ),
            sortDescFirst: true,
            cell: ({ row }) => (
                <Text size="sm" className="block py-1 whitespace-nowrap" render={<span />}>
                    {complexityLabel(row.original.complexity)}
                </Text>
            ),
        },
    ]
}

// Every cell starts at the top of its row, so the one-line cells stay level with the metric name when a row opens.
const topAlignedRow = (): string => '[&>td]:align-top'

// The API and the classic layout name these rows proposed metrics. This layout names them suggested,
// because the Metrics tab already uses Proposed for the status of a metric that waits for approval.
export function CatalogSuggestedMetricsTable(): JSX.Element {
    const { visibleSuggestions } = useValues(catalogSuggestedMetricsLogic)
    const [expandedKeys, setExpandedKeys] = useState<Set<string>>(() => new Set())

    const columns = useMemo(() => proposedColumns(expandedKeys), [expandedKeys])
    const toggle = useCallback((row: ProposedRow): void => {
        setExpandedKeys((current) => {
            const next = new Set(current)
            if (next.has(row.key)) {
                next.delete(row.key)
            } else {
                next.add(row.key)
            }
            return next
        })
    }, [])

    return (
        // pinned: autocapture reads the data-attr values in this file, so they keep the name of the tab that first held this table
        <div className="@container min-w-0" data-attr="data-catalog-governance-proposed">
            <DataTable
                columns={columns}
                data={visibleSuggestions}
                getRowId={(row) => row.key}
                // The table shows its pager for one page too, so a list that fits one page gets no page size.
                pageSize={visibleSuggestions.length > CATALOG_LAYER_PAGE_SIZE ? CATALOG_LAYER_PAGE_SIZE : undefined}
                size="sm"
                fullWidth
                onRowClick={toggle}
                rowClassName={topAlignedRow}
            />
        </div>
    )
}
