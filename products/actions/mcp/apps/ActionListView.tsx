import { type ReactElement, type ReactNode } from 'react'

import { Badge, DataTable, type DataTableColumn, formatDate, ListDetailView, Stack } from '@posthog/mosaic'

import { ActionView, type ActionData } from './ActionView'

export interface ActionListData {
    results: ActionData[]
    _posthogUrl?: string
}

export interface ActionListViewProps {
    data: ActionListData
    onActionClick?: (action: ActionData) => Promise<ActionData | null>
}

export function ActionListView({ data, onActionClick }: ActionListViewProps): ReactElement {
    return (
        <ListDetailView<ActionData>
            onItemClick={onActionClick}
            backLabel="All actions"
            getItemName={(action) => action.name}
            renderDetail={(action) => <ActionView action={action} />}
            renderList={(handleClick) => {
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
                        render: (row): ReactNode => (
                            <span className="text-text-secondary">{row.steps?.length ?? 0}</span>
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
            }}
        />
    )
}
