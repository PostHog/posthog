import { type ReactElement, type ReactNode } from 'react'

import { Badge, DataTable, type DataTableColumn, formatDate, ListDetailView, Stack } from '@posthog/mosaic'

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
                                <button
                                    onClick={() => handleClick(row)}
                                    className="text-link underline decoration-border-primary hover:decoration-link cursor-pointer text-left transition-colors"
                                >
                                    {row.name}
                                </button>
                            ) : (
                                row.name
                            ),
                    },
                    {
                        key: 'is_static',
                        header: 'Type',
                        render: (row): ReactNode => (
                            <Badge variant={row.is_static ? 'neutral' : 'info'} size="sm">
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
                            <span className="text-text-secondary tabular-nums">
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
                                <span className="text-text-secondary">{formatDate(row.created_at)}</span>
                            ) : (
                                <span className="text-text-secondary">&mdash;</span>
                            ),
                    },
                ]

                return (
                    <div className="p-4">
                        <Stack gap="sm">
                            <div className="flex items-center justify-between">
                                <span className="text-sm text-text-secondary">
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
                        </Stack>
                    </div>
                )
            }}
        />
    )
}
