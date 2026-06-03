import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, ListDetailView, formatDate } from '@posthog/mcp-ui'
import { Badge, Button } from '@posthog/quill'

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
                        key: 'tags',
                        header: 'Tags',
                        render: (row): ReactNode =>
                            row.tags?.length ? (
                                <div className="flex gap-1 flex-wrap">
                                    {row.tags.map((tag) => (
                                        <Badge key={tag}>{tag}</Badge>
                                    ))}
                                </div>
                            ) : (
                                <span className="text-muted-foreground">&mdash;</span>
                            ),
                    },
                    {
                        key: 'steps' as keyof ActionData,
                        header: 'Steps',
                        render: (row): ReactNode => (
                            <span className="text-muted-foreground">{row.steps?.length ?? 0}</span>
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
                        </div>
                    </div>
                )
            }}
        />
    )
}
