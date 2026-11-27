import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'

import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconChevronRight, IconOpenSidebar, IconSearch } from '@posthog/icons'
import {
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
    cn,
} from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { QuillTableSkeleton } from 'lib/components/QuillTableSkeleton/QuillTableSkeleton'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { urls } from 'scenes/urls'

import { warningDocsUrl, warningTypeLabel } from './ingestionWarningDisplay'
import { IngestionWarningSummary, ingestionWarningsLogic } from './ingestionWarningsLogic'
import { QuillNestedWarnings } from './QuillNestedWarnings'

const HedgehogReadingIsMagic = pngHoggie(readingIsMagicPng)

type Columns = DataTableProps<IngestionWarningSummary, unknown>['columns']

/** Quill version of the ingestion warnings list, which the page renders under `today-rail-nav`. */
export function QuillIngestionWarnings(): JSX.Element {
    const { data, dataLoading, summaryDatasets, dates, searchQuery, showProductIntro } =
        useValues(ingestionWarningsLogic)
    const { setSearchQuery } = useActions(ingestionWarningsLogic)
    const [expandedTypes, setExpandedTypes] = useState<ReadonlySet<string>>(new Set())

    const toggleExpanded = useCallback((summary: IngestionWarningSummary): void => {
        setExpandedTypes((current) => {
            const next = new Set(current)
            if (!next.delete(summary.type)) {
                next.add(summary.type)
            }
            return next
        })
    }, [])

    const rowClassName = useCallback(
        (summary: IngestionWarningSummary): string | undefined =>
            expandedTypes.has(summary.type) ? '[&>td]:align-top' : undefined,
        [expandedTypes]
    )

    // The Lemon table opens on the most recent warning, so the rows start in that order here too.
    const sortedData = useMemo(
        () => [...data].sort((a, b) => new Date(b.lastSeen).getTime() - new Date(a.lastSeen).getTime()),
        [data]
    )

    const columns = useMemo<Columns>(
        () => [
            {
                id: 'type',
                header: 'Warning',
                enableSorting: false,
                meta: { expand: true },
                cell: ({ row }) => {
                    const summary = row.original
                    const expanded = expandedTypes.has(summary.type)
                    return (
                        <div className="flex min-w-0 flex-col">
                            <div className="flex min-w-0 items-center gap-1">
                                <Button
                                    size="icon-xs"
                                    aria-expanded={expanded}
                                    aria-label={`${expanded ? 'Hide' : 'Show'} ${warningTypeLabel(summary.type)} warnings`}
                                    onClick={() => toggleExpanded(summary)}
                                >
                                    <IconChevronRight
                                        className={cn('transition-transform motion-reduce:transition-none', {
                                            'rotate-90': expanded,
                                        })}
                                    />
                                </Button>
                                <span className="min-w-0 whitespace-normal">
                                    {warningTypeLabel(summary.type)} (
                                    <Button
                                        variant="link"
                                        size="inline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={warningDocsUrl(summary.type)} target="_blank" />}
                                    >
                                        docs
                                    </Button>
                                    )
                                </span>
                            </div>
                            {expanded && <QuillNestedWarnings warnings={summary.warnings} />}
                        </div>
                    )
                },
            },
            {
                id: 'graph',
                header: 'Graph',
                enableSorting: false,
                cell: ({ row }) => (
                    <Sparkline className="h-8" labels={dates} data={summaryDatasets[row.original.type]} />
                ),
            },
            {
                id: 'count',
                accessorKey: 'count',
                header: 'Events',
                meta: { align: 'right' },
                sortDescFirst: true,
            },
            {
                id: 'lastSeen',
                accessorFn: (summary) => new Date(summary.lastSeen).getTime(),
                header: 'Last Seen',
                meta: { align: 'right' },
                sortDescFirst: true,
                cell: ({ row }) => <TZLabel time={row.original.lastSeen} showSeconds />,
            },
        ],
        [expandedTypes, toggleExpanded, dates, summaryDatasets]
    )

    if (showProductIntro) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia>
                        <HedgehogReadingIsMagic className="w-40" />
                    </EmptyMedia>
                    <EmptyTitle>Nice! No ingestion warnings in the past 30 days</EmptyTitle>
                    <EmptyDescription>
                        Your incoming events look clean. If we detect any issues with your data, we'll show them here.
                    </EmptyDescription>
                </EmptyHeader>
                <EmptyContent className="flex-row justify-center">
                    <Button
                        variant="primary"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.eventDefinitions()} />}
                        data-attr="ingestion-warnings-empty-state-events"
                    >
                        Explore your events
                        <IconOpenSidebar />
                    </Button>
                    <Button
                        variant="outline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://posthog.com/docs/data/data-management#ingestion-warnings?utm_medium=in-product&utm_campaign=empty-state-docs-link"
                                target="_blank"
                            />
                        }
                        data-attr="product-introduction-docs-link"
                    >
                        Learn more
                        <IconOpenSidebar />
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    const renderBody = (): JSX.Element => {
        if (dataLoading && data.length === 0) {
            return <QuillTableSkeleton label="Loading ingestion warnings" />
        }
        if (data.length === 0) {
            return (
                <Empty data-attr="ingestion-warnings-no-match">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconSearch />
                        </EmptyMedia>
                        <EmptyTitle>No ingestion warnings match your search</EmptyTitle>
                        <EmptyDescription>Try a different person, session ID or warning type.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button variant="outline" onClick={() => setSearchQuery('')}>
                            Clear search
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        return (
            <Card size="sm" flush className="pt-0">
                <DataTable
                    columns={columns}
                    data={sortedData}
                    fullWidth
                    size="sm"
                    getRowId={(summary) => summary.type}
                    onRowClick={toggleExpanded}
                    rowClassName={rowClassName}
                />
            </Card>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <AnalyticsSearchInput
                value={searchQuery}
                onChange={setSearchQuery}
                label="Search ingestion warnings"
                placeholder="Try pasting a person or session id or an ingestion warning type"
                dataAttr="ingestion-warnings-search"
                className="w-full"
            />
            {renderBody()}
        </div>
    )
}
