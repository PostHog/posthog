import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

import { BackButton, Badge, DataTable, type DataTableColumn, formatDate, LoadingState, Stack } from '@posthog/mosaic'

import { ActionView, type ActionData } from './ActionView'

export interface ActionListData {
    results: ActionData[]
    _posthogUrl?: string
}

export interface ActionListViewProps {
    data: ActionListData
    onActionClick?: (action: ActionData) => Promise<ActionData | null>
}

type ViewState = { view: 'list' } | { view: 'loading'; name: string } | { view: 'detail'; action: ActionData }

export function ActionListView({ data, onActionClick }: ActionListViewProps): ReactElement {
    const [viewState, setViewState] = useState<ViewState>({ view: 'list' })

    const handleClick = useCallback(
        async (action: ActionData) => {
            if (!onActionClick) {
                return
            }

            setViewState({ view: 'loading', name: action.name })
            const detail = await onActionClick(action).catch((error) => {
                console.error('Error loading action detail:', error)
                return null
            })

            if (detail) {
                setViewState({ view: 'detail', action: detail })
            } else {
                setViewState({ view: 'list' })
            }
        },
        [onActionClick]
    )

    const handleBack = useCallback(() => setViewState({ view: 'list' }), [])

    if (viewState.view === 'loading') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All actions" />
                    <LoadingState label={viewState.name} />
                </Stack>
            </div>
        )
    }

    if (viewState.view === 'detail') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label="All actions" />
                    <ActionView action={viewState.action} />
                </Stack>
            </div>
        )
    }

    const columns: DataTableColumn<ActionData>[] = [
        {
            key: 'name',
            header: 'Name',
            sortable: true,
            render: (row): ReactNode =>
                onActionClick ? (
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
            key: 'tags',
            header: 'Tags',
            render: (row): ReactNode =>
                row.tags?.length ? (
                    <div className="flex gap-1 flex-wrap">
                        {row.tags.map((tag) => (
                            <Badge key={tag} variant="neutral" size="sm">
                                {tag}
                            </Badge>
                        ))}
                    </div>
                ) : (
                    <span className="text-text-secondary">&mdash;</span>
                ),
        },
        {
            key: 'steps' as keyof ActionData,
            header: 'Steps',
            render: (row): ReactNode => <span className="text-text-secondary">{row.steps?.length ?? 0}</span>,
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
                        {data.results.length} action{data.results.length === 1 ? '' : 's'}
                    </span>
                </div>
                <DataTable<ActionData>
                    columns={columns}
                    data={data.results}
                    pageSize={10}
                    defaultSort={{ key: 'name', direction: 'asc' }}
                    emptyMessage="No actions found"
                />
            </Stack>
        </div>
    )
}
