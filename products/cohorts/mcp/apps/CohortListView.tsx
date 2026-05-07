import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView, formatDate } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

import { CohortView, type CohortData } from './CohortView'

export interface CohortListData {
    results: CohortData[]
    _posthogUrl?: string
}

export interface CohortListViewProps {
    data: CohortListData
    onCohortClick?: (cohort: CohortData) => Promise<CohortData | null>
}

export function CohortListView({ data, onCohortClick }: CohortListViewProps): ReactElement {
    return (
        <ListDetailView<CohortData>
            onItemClick={onCohortClick}
            backLabel="All cohorts"
            getItemName={(cohort) => cohort.name}
            renderDetail={(cohort) => <CohortView cohort={cohort} />}
            renderList={(handleClick) => {
                const columns: DataTableColumn<CohortData>[] = [
                    {
                        key: 'name',
                        header: 'Name',
                        sortable: true,
                        render: (row): ReactNode =>
                            onCohortClick ? (
                                <Button
                                    variant="link"
                                    size="sm"
                                    onClick={() => handleClick(row)}
                                    className="h-auto px-0 text-left"
                                >
                                    {row.name}
                                </Button>
                            ) : (
                                row.name
                            ),
                    },
                    {
                        key: 'is_static',
                        header: 'Type',
                        render: (row): ReactNode => (
                            <Badge variant={row.is_static ? 'default' : 'info'}>
                                {row.is_static ? 'Static' : 'Dynamic'}
                            </Badge>
                        ),
                    },
                    {
                        key: 'count',
                        header: 'Persons',
                        align: 'right',
                        sortable: true,
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground tabular-nums">
                                {row.count != null ? row.count.toLocaleString() : '\u2014'}
                            </span>
                        ),
                    },
                    {
                        key: 'created_at',
                        header: 'Created',
                        sortable: true,
                        render: (row): ReactNode =>
                            row.created_at ? (
                                <span className="text-muted-foreground">{formatDate(row.created_at)}</span>
                            ) : (
                                <span className="text-muted-foreground">&mdash;</span>
                            ),
                    },
                ]

                return (
                    <div className="p-4">
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-muted-foreground">
                                    {data.results.length} cohort{data.results.length === 1 ? '' : 's'}
                                </span>
                            </div>
                            <DataTable<CohortData>
                                columns={columns}
                                data={data.results}
                                pageSize={10}
                                defaultSort={{ key: 'name', direction: 'asc' }}
                                emptyMessage="No cohorts found"
                            />
                        </div>
                    </div>
                )
            }}
        />
    )
}
