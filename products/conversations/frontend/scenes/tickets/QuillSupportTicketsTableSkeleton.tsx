import { Card, Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill'

import { type TicketColumnKey, ticketColumnLabel } from './ticketColumns'

/** Holds the table's layout while the first page of tickets loads. */
export function QuillSupportTicketsTableSkeleton({ columns }: { columns: TicketColumnKey[] }): JSX.Element {
    return (
        <Card size="sm" flush className="pt-0" aria-busy aria-label="Loading tickets">
            <Table fullWidth size="sm">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-8" />
                        {columns.map((key) => (
                            <TableHead key={key} expand={key === 'last_message'}>
                                {ticketColumnLabel(key)}
                            </TableHead>
                        ))}
                    </TableRow>
                </TableHeader>
                <TableBody aria-hidden>
                    {Array.from({ length: 8 }, (_, index) => (
                        <TableRow key={index}>
                            <TableCell>
                                <Skeleton className="size-4" />
                            </TableCell>
                            {columns.map((key) => (
                                <TableCell key={key} expand={key === 'last_message'}>
                                    <div className="flex h-6 items-center gap-2">
                                        {key === 'customer' && <Skeleton className="size-5 shrink-0 rounded-full" />}
                                        <Skeleton
                                            className={
                                                key === 'last_message'
                                                    ? index % 2 === 0
                                                        ? 'h-3 w-56'
                                                        : 'h-3 w-40'
                                                    : key === 'ticket_number'
                                                      ? 'h-3 w-8'
                                                      : 'h-3 w-16'
                                            }
                                        />
                                    </div>
                                </TableCell>
                            ))}
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </Card>
    )
}
