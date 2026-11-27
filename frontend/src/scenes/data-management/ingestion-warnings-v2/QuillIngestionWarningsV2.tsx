import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'

import { IconChevronRight, IconRefresh, IconSearch } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    DataTable,
    DataTableProps,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { QuillTableSkeleton } from 'lib/components/QuillTableSkeleton/QuillTableSkeleton'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'

import { warningDocsUrl } from '../ingestion-warnings/ingestionWarningDisplay'
import { WARNING_TYPE_TO_DESCRIPTION } from '../ingestion-warnings/ingestionWarningTypes'
import { QuillIngestionWarningsIntro } from '../ingestion-warnings/QuillIngestionWarningsIntro'
import { SEVERITY_BAR_COLORS } from './ingestionWarningSeverity'
import {
    IngestionWarningV2Summary,
    IngestionWarningsOrderBy,
    ingestionWarningsV2Logic,
} from './ingestionWarningsV2Logic'
import { QuillIngestionWarningsV2FilterMenu } from './QuillIngestionWarningsV2FilterMenu'
import { QuillIngestionWarningsV2SummaryTiles } from './QuillIngestionWarningsV2SummaryTiles'
import { QuillWarningSamples } from './QuillWarningSamples'

type Columns = DataTableProps<IngestionWarningV2Summary, unknown>['columns']

const SEVERITY_TO_BADGE_VARIANT: Record<string, 'destructive' | 'warning' | 'default'> = {
    error: 'destructive',
    warning: 'warning',
    info: 'default',
}

function FilterBadge({
    tooltip,
    variant,
    onClick,
    children,
}: {
    tooltip: string
    variant: 'destructive' | 'warning' | 'default' | 'info'
    onClick: () => void
    children: React.ReactNode
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<button type="button" className="cursor-pointer" onClick={onClick} />}>
                <Badge variant={variant}>{children}</Badge>
            </TooltipTrigger>
            <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
    )
}

/** Quill version of the v2 ingestion warnings list, which the page renders under `today-rail-nav`. */
export function QuillIngestionWarningsV2(): JSX.Element {
    const { warnings, warningsLoading, summaryDatasets, bucketLabels, filters, showProductIntro, hasActiveFilters } =
        useValues(ingestionWarningsV2Logic)
    const { setFilters, loadWarnings } = useActions(ingestionWarningsV2Logic)
    const [expandedTypes, setExpandedTypes] = useState<ReadonlySet<string>>(new Set())

    const toggleExpanded = useCallback((summary: IngestionWarningV2Summary): void => {
        setExpandedTypes((current) => {
            const next = new Set(current)
            if (!next.delete(summary.type)) {
                next.add(summary.type)
            }
            return next
        })
    }, [])

    const rowClassName = useCallback(
        (summary: IngestionWarningV2Summary): string | undefined =>
            expandedTypes.has(summary.type) ? '[&>td]:align-top' : undefined,
        [expandedTypes]
    )

    const columns = useMemo<Columns>(
        () => [
            {
                id: 'severity',
                header: 'Severity',
                enableSorting: false,
                cell: ({ row }) => {
                    const { severity } = row.original
                    return (
                        <div className="flex items-center gap-2">
                            <div className={cn('h-4 w-1 rounded-full', SEVERITY_BAR_COLORS[severity] ?? 'bg-muted')} />
                            <FilterBadge
                                tooltip={`Only show ${severity} warnings`}
                                variant={SEVERITY_TO_BADGE_VARIANT[severity] ?? 'default'}
                                onClick={() => setFilters({ severity })}
                            >
                                {severity}
                            </FilterBadge>
                        </div>
                    )
                },
            },
            {
                id: 'type',
                header: 'Warning',
                enableSorting: false,
                meta: { expand: true },
                cell: ({ row }) => {
                    const summary = row.original
                    const expanded = expandedTypes.has(summary.type)
                    const description = WARNING_TYPE_TO_DESCRIPTION[summary.type]
                    return (
                        <div className="flex min-w-0 flex-col">
                            <div className="flex min-w-0 items-start gap-1">
                                <Button
                                    size="icon-xs"
                                    aria-expanded={expanded}
                                    aria-label={`${expanded ? 'Hide' : 'Show'} ${summary.type} samples`}
                                    onClick={() => toggleExpanded(summary)}
                                >
                                    <IconChevronRight
                                        className={cn('transition-transform motion-reduce:transition-none', {
                                            'rotate-90': expanded,
                                        })}
                                    />
                                </Button>
                                <div className="flex min-w-0 flex-col gap-0.5 whitespace-normal">
                                    <span className="font-mono text-xs font-semibold">{summary.type}</span>
                                    <span className="text-xs text-muted-foreground">
                                        {description ? `${description} — ` : ''}
                                        <Button
                                            variant="link"
                                            size="inline"
                                            nativeButton={false}
                                            render={<LinkPrimitive to={warningDocsUrl(summary.type)} target="_blank" />}
                                        >
                                            docs
                                        </Button>
                                    </span>
                                </div>
                            </div>
                            {expanded && <QuillWarningSamples summary={summary} />}
                        </div>
                    )
                },
            },
            {
                id: 'category',
                header: 'Category',
                enableSorting: false,
                cell: ({ row }) => (
                    <FilterBadge
                        tooltip={`Only show ${row.original.category} warnings`}
                        variant="info"
                        onClick={() => setFilters({ category: row.original.category })}
                    >
                        {row.original.category}
                    </FilterBadge>
                ),
            },
            {
                id: 'graph',
                header: 'Graph',
                enableSorting: false,
                cell: ({ row }) => (
                    <div className="w-40">
                        <Sparkline
                            className="h-8 w-full"
                            labels={bucketLabels}
                            data={summaryDatasets[row.original.type]}
                        />
                    </div>
                ),
            },
            {
                id: 'count',
                accessorKey: 'count',
                header: 'Events',
                meta: { align: 'right' },
                sortDescFirst: true,
                cell: ({ row }) => humanFriendlyNumber(row.original.count),
            },
            {
                id: 'last_seen',
                accessorKey: 'last_seen',
                header: 'Last Seen',
                meta: { align: 'right' },
                sortDescFirst: true,
                cell: ({ row }) => (
                    <span className="font-mono text-xs whitespace-nowrap">
                        <TZLabel time={row.original.last_seen} showSeconds />
                    </span>
                ),
            },
        ],
        [expandedTypes, toggleExpanded, setFilters, bucketLabels, summaryDatasets]
    )

    if (showProductIntro) {
        return (
            <QuillIngestionWarningsIntro
                title={`Nice! No ingestion warnings in the past ${filters.window}`}
                eventsDataAttr="ingestion-warnings-v2-empty-state-events"
            />
        )
    }

    const renderBody = (): JSX.Element => {
        if (warningsLoading && warnings.length === 0) {
            return <QuillTableSkeleton label="Loading ingestion warnings" />
        }
        if (warnings.length === 0) {
            return (
                <Empty data-attr="ingestion-warnings-v2-no-match">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconSearch />
                        </EmptyMedia>
                        <EmptyTitle>No ingestion warnings match your search or filters</EmptyTitle>
                        <EmptyDescription>Try a different search, time range or filter.</EmptyDescription>
                    </EmptyHeader>
                    {hasActiveFilters && (
                        <EmptyContent>
                            <Button
                                variant="outline"
                                onClick={() => setFilters({ q: '', category: null, severity: null })}
                            >
                                Clear search and filters
                            </Button>
                        </EmptyContent>
                    )}
                </Empty>
            )
        }
        return (
            <Card size="sm" flush className="pt-0">
                <DataTable
                    columns={columns}
                    data={warnings}
                    fullWidth
                    size="sm"
                    getRowId={(summary) => summary.type}
                    onRowClick={toggleExpanded}
                    rowClassName={rowClassName}
                    // The API sorts the rows, always in descending order.
                    sorting={[{ id: filters.orderBy, desc: true }]}
                    onSortingChange={(next) => {
                        const orderBy = next[0]?.id
                        if (orderBy === 'count' || orderBy === 'last_seen') {
                            setFilters({ orderBy: orderBy as IngestionWarningsOrderBy })
                        }
                    }}
                />
            </Card>
        )
    }

    return (
        <QuillSurfaceContext.Provider value={true}>
            <div className="flex flex-col gap-2">
                <QuillIngestionWarningsV2SummaryTiles />
                <div className="flex items-center gap-2">
                    <AnalyticsSearchInput
                        value={filters.q}
                        onChange={(q) => setFilters({ q })}
                        label="Search ingestion warnings"
                        placeholder="Try pasting a person or session id or an ingestion warning type"
                        dataAttr="ingestion-warnings-v2-search"
                        className="min-w-0 flex-1"
                    />
                    <QuillIngestionWarningsV2FilterMenu />
                    <Button
                        variant="outline"
                        size="icon"
                        tooltip="Refresh"
                        aria-label="Refresh"
                        loading={warningsLoading}
                        onClick={() => loadWarnings()}
                    >
                        <IconRefresh />
                    </Button>
                </div>
                {renderBody()}
            </div>
        </QuillSurfaceContext.Provider>
    )
}
