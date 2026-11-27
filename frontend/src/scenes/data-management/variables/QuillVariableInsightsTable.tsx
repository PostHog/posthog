import { useMemo } from 'react'

import { Button, Card, DataTable, DataTableProps, Empty, EmptyHeader, EmptyTitle, Text } from '@posthog/quill'

import { QuillTableSkeleton } from 'lib/components/QuillTableSkeleton/QuillTableSkeleton'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { InsightModel } from '~/types'

type Columns = DataTableProps<InsightModel, unknown>['columns']

function NoValue({ children = '—' }: { children?: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span />}>
            {children}
        </Text>
    )
}

export interface QuillVariableInsightsTableProps {
    insights: InsightModel[]
    loading: boolean
}

/** Quill sibling of the edit page's "Insights using this variable" `LemonTable`. */
export function QuillVariableInsightsTable({ insights, loading }: QuillVariableInsightsTableProps): JSX.Element {
    const columns = useMemo<Columns>(
        () => [
            {
                id: 'name',
                header: 'Name',
                meta: { expand: true },
                cell: ({ row }) => (
                    <div className="flex min-w-0 flex-col">
                        {/* The table pulls a borderless Button that sits directly in a cell 0.5rem to the left, to
                            offset its padding. This inline link has no padding, so the wrapper keeps it in line
                            with the header. */}
                        <div className="flex min-w-0">
                            <Button
                                variant="link-foreground"
                                size="inline"
                                nativeButton={false}
                                left
                                render={<LinkPrimitive to={urls.insightView(row.original.short_id)} />}
                                className="min-w-0 max-w-full font-semibold"
                            >
                                <span className="truncate">{row.original.name || <i>Untitled</i>}</span>
                            </Button>
                        </div>
                        {row.original.description && (
                            <Text size="xs" variant="muted" render={<span />} className="truncate">
                                {row.original.description}
                            </Text>
                        )}
                    </div>
                ),
            },
            {
                id: 'created_at',
                header: 'Created',
                meta: { align: 'right' },
                cell: ({ row }) =>
                    row.original.created_at ? (
                        <div className="whitespace-nowrap text-right">
                            <TZLabel time={row.original.created_at} />
                        </div>
                    ) : (
                        <NoValue />
                    ),
            },
            {
                id: 'last_modified_at',
                header: 'Last modified',
                cell: ({ row }) => (
                    <div className="whitespace-nowrap">
                        {row.original.last_modified_at && <TZLabel time={row.original.last_modified_at} />}
                    </div>
                ),
            },
            {
                id: 'last_viewed_at',
                header: 'Last viewed',
                cell: ({ row }) => (
                    <div className="whitespace-nowrap">
                        {row.original.last_viewed_at ? (
                            <TZLabel time={row.original.last_viewed_at} />
                        ) : (
                            <NoValue>Never</NoValue>
                        )}
                    </div>
                ),
            },
        ],
        []
    )

    if (loading && insights.length === 0) {
        return <QuillTableSkeleton label="Loading insights" />
    }
    if (insights.length === 0) {
        return (
            <Empty data-attr="variable-insights-empty">
                <EmptyHeader>
                    <EmptyTitle>No insights use this variable</EmptyTitle>
                </EmptyHeader>
            </Empty>
        )
    }
    return (
        <Card size="sm" flush className="pt-0">
            <div data-attr="variable-insights-table">
                <DataTable
                    columns={columns}
                    data={insights}
                    fullWidth
                    size="sm"
                    getRowId={(insight) => String(insight.id)}
                />
            </div>
        </Card>
    )
}
