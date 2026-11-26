import { type ColumnDef } from '@tanstack/react-table'

import { IconCheck } from '@posthog/icons'
import {
    DataTable,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Heading,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { IconLink } from 'lib/lemon-ui/icons'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'

import type { AggregatedUtmSource } from '../../logic/utmAuditLogic'
import { QuillTableLoadingRows } from '../common/QuillTableLoadingRows'
import { QuillUtmAuditActionsMenu } from './QuillUtmAuditActionsMenu'
import { formatNumber, sourceLabel } from './utmAuditLabels'

const COLUMNS: ColumnDef<AggregatedUtmSource, unknown>[] = [
    {
        id: 'utm_source',
        header: 'utm_source',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => <span className="font-mono">{row.original.utm_source}</span>,
    },
    {
        id: 'event_count',
        accessorFn: (row: AggregatedUtmSource) => row.event_count,
        header: 'Pageviews',
        sortDescFirst: false,
        cell: ({ row }) => formatNumber(row.original.event_count),
    },
    {
        id: 'integration',
        header: 'Integration',
        enableSorting: false,
        cell: ({ row }) =>
            row.original.integration ? (
                <span>{sourceLabel(row.original.integration)}</span>
            ) : (
                <span className="text-muted-foreground">—</span>
            ),
    },
    {
        id: 'match',
        header: '',
        enableSorting: false,
        cell: ({ row }) =>
            row.original.mapped ? (
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex" />}>
                        {row.original.match_type === 'mapped' ? (
                            <IconLink className="size-4 text-primary" />
                        ) : (
                            <IconCheck className="size-4 text-success-foreground" />
                        )}
                    </TooltipTrigger>
                    <TooltipContent>
                        {row.original.match_type === 'mapped' ? 'Manually mapped' : 'Default integration source'}
                    </TooltipContent>
                </Tooltip>
            ) : null,
    },
    {
        id: 'actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) => <QuillUtmAuditActionsMenu columnName="Source" value={row.original.utm_source} />,
    },
]

export function QuillUtmAuditSourceTab({
    loading,
    sources,
    utmSearch,
    onUtmSearchChange,
}: {
    loading: boolean
    sources: AggregatedUtmSource[]
    utmSearch: string
    onUtmSearchChange: (search: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Heading size="sm" render={<h4 className="m-0" />}>
                    UTM sources
                </Heading>
                <AnalyticsSearchInput
                    value={utmSearch}
                    onChange={onUtmSearchChange}
                    label="Search UTM sources"
                    placeholder="Search..."
                    dataAttr="marketing-utm-audit-source-search"
                    className="w-48 max-w-full"
                />
            </div>
            <div className={cn('transition-opacity', loading && 'opacity-60')} aria-busy={loading || undefined}>
                <DataTable
                    className="max-h-175"
                    stickyHeader
                    fullWidth
                    size="sm"
                    columns={COLUMNS}
                    data={sources}
                    getRowId={(record) => record.utm_source}
                    empty={
                        loading ? (
                            <QuillTableLoadingRows />
                        ) : (
                            <Empty>
                                <EmptyHeader>
                                    <EmptyDescription>No UTM sources found</EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        )
                    }
                />
            </div>
        </div>
    )
}
