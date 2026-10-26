import { Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill'

import type { AnalyticsListColumns } from './AnalyticsListColumns'

const COLUMN_LABELS: Record<string, string> = {
    name: 'Title',
    space: 'Collection',
    tags: 'Tags',
    owner: 'Owner',
    last_viewed: 'Last viewed',
    created: 'Created',
}

export function AnalyticsListSkeleton({ columns }: { columns: AnalyticsListColumns }): JSX.Element {
    return (
        <div aria-busy aria-label="Loading analytics">
            <Table
                fullWidth
                size="sm"
                className="w-full min-w-0 **:data-expand:min-w-64 **:data-expand:max-w-0 **:data-[slot=table]:min-w-208"
            >
                <TableHeader>
                    <TableRow>
                        {columns.map((column) => (
                            <TableHead key={column.id} expand={column.id === 'name'}>
                                {COLUMN_LABELS[column.id ?? '']}
                            </TableHead>
                        ))}
                    </TableRow>
                </TableHeader>
                <TableBody aria-hidden>
                    {Array.from({ length: 6 }, (_, index) => (
                        <TableRow key={index}>
                            {columns.map((column) => {
                                if (column.id === 'name') {
                                    return (
                                        <TableCell key={column.id} expand>
                                            <div className="flex h-6 min-w-48 items-center gap-2">
                                                <Skeleton className="size-4 shrink-0" />
                                                <Skeleton className={index % 2 === 0 ? 'h-3 w-40' : 'h-3 w-28'} />
                                            </div>
                                        </TableCell>
                                    )
                                }
                                if (column.id === 'space' || column.id === 'owner') {
                                    return (
                                        <TableCell key={column.id}>
                                            <div className="flex w-36 items-center gap-2">
                                                <Skeleton className="size-5 shrink-0 rounded-full" />
                                                <Skeleton className="h-3 w-20" />
                                            </div>
                                        </TableCell>
                                    )
                                }
                                if (column.id === 'tags') {
                                    return (
                                        <TableCell key={column.id}>
                                            <div className="flex w-36 gap-1">
                                                <Skeleton className="h-5 w-14" />
                                                <Skeleton className="h-5 w-12" />
                                            </div>
                                        </TableCell>
                                    )
                                }
                                return (
                                    <TableCell key={column.id}>
                                        <div className={column.id === 'move' ? 'w-8' : 'w-24'}>
                                            <Skeleton className={column.id === 'move' ? 'size-4' : 'h-3 w-20'} />
                                        </div>
                                    </TableCell>
                                )
                            })}
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
    )
}
