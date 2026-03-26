import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

import { BackButton, Badge, DataTable, type DataTableColumn, formatDate, LoadingState, Stack } from '@posthog/mosaic'

import { CohortView, type CohortData } from './CohortView'

export interface CohortListData {
    results: CohortData[]
    _posthogUrl?: string
}

export interface CohortListViewProps {
    data: CohortListData
    onCohortClick?: (cohort: CohortData) => Promise<CohortData | null>
}

type ViewState = { view: 'list' } | { view: 'loading'; name: string } | { view: 'detail'; cohort: CohortData }

export function CohortListView({ data, onCohortClick }: CohortListViewProps): ReactElement {
    const [viewState, setViewState] = useState<ViewState>({ view: 'list' })

    const handleClick = useCallback(
        async (cohort: CohortData) => {
            if (!onCohortClick) {
                return
            }
            setViewState({ view: 'loading', name: cohort.name })
            const detail = await onCohortClick(cohort).catch((error) => {
                console.error('Error loading cohort detail:', error)
                return null
            })

            if (detail) {
                setViewState({ view: 'detail', cohort: detail })
            } else {
                setViewState({ view: 'list' })
            }
        },
        [onCohortClick]
    )

    const handleBack = useCallback(() => setViewState({ view: 'list' }), [])

    if (viewState.view === 'loading') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All cohorts" />
                    <LoadingState label={viewState.name} />
                </Stack>
            </div>
        )
    }

    if (viewState.view === 'detail') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All cohorts" />
                    <CohortView cohort={viewState.cohort} />
                </Stack>
            </div>
        )
    }

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
}
