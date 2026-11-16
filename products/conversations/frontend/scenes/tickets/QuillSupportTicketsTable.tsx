import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useMemo } from 'react'

import { Card, DataTable, type DataTableProps, cn } from '@posthog/quill'

import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'

import { type Ticket } from '../../types'
import { QuillSupportTicketsEmptyState } from './QuillSupportTicketsEmptyState'
import { QuillSupportTicketsLoadError } from './QuillSupportTicketsLoadError'
import { QuillSupportTicketsTableSkeleton } from './QuillSupportTicketsTableSkeleton'
import { buildQuillTicketColumns } from './quillTicketColumns'
import { SUPPORT_TICKETS_PAGE_SIZE, supportTicketsSceneLogic } from './supportTicketsSceneLogic'
import { visibleTicketColumnKeys } from './ticketColumns'
import { ticketColumnsLogic } from './ticketColumnsLogic'
import { openTicketRow, ticketRowUrl } from './ticketRowNavigation'

type TicketTableProps = DataTableProps<Ticket, unknown>

const getTicketId = (ticket: Ticket): string => ticket.id
const unreadRowClassName = (ticket: Ticket): string | undefined =>
    ticket.unread_team_count > 0 ? 'bg-fill-hover' : undefined

export function QuillSupportTicketsTable(): JSX.Element {
    const {
        tickets,
        ticketsLoading,
        ticketsLoadState,
        currentPage,
        pageCount,
        totalCount,
        sorting,
        selectedTicketIds,
        emptyStateKind,
        aiEnabled,
    } = useValues(supportTicketsSceneLogic)
    const { setCurrentPage, setSorting, setSelectedTicketIds, clearFiltersKeepingSearch, loadTickets } =
        useActions(supportTicketsSceneLogic)
    const { visibleColumns } = useValues(ticketColumnsLogic)
    const { searchParams } = useValues(router)

    const columns = useMemo(
        () =>
            buildQuillTicketColumns(visibleColumns, {
                aiEnabled,
                embedded: false,
                ticketUrl: (ticket) => ticketRowUrl(ticket, searchParams, false),
            }),
        [visibleColumns, aiEnabled, searchParams]
    )
    const rowSelection = useMemo<NonNullable<TicketTableProps['rowSelection']>>(
        () => Object.fromEntries(selectedTicketIds.map((id) => [id, true])),
        [selectedTicketIds]
    )
    const tableSorting = useMemo<NonNullable<TicketTableProps['sorting']>>(
        () => (sorting ? [{ id: sorting.columnKey, desc: sorting.order === -1 }] : []),
        [sorting]
    )
    const onRowClick = useCallback<NonNullable<TicketTableProps['onRowClick']>>(
        (ticket, event) => openTicketRow(ticketRowUrl(ticket, searchParams, false), event.metaKey || event.ctrlKey),
        [searchParams]
    )
    const empty = useMemo(
        () => (
            <QuillSupportTicketsEmptyState
                kind={emptyStateKind}
                onSearchWithoutFilters={() => clearFiltersKeepingSearch()}
            />
        ),
        [emptyStateKind, clearFiltersKeepingSearch]
    )

    // A retry after a failed first load shows the skeleton again, not the error it is replacing.
    if (ticketsLoadState === 'unloaded' || (ticketsLoading && ticketsLoadState === 'failed')) {
        return (
            <QuillSupportTicketsTableSkeleton
                columns={visibleTicketColumnKeys(visibleColumns, { aiEnabled, embedded: false })}
            />
        )
    }
    if (ticketsLoadState === 'failed' && tickets.length === 0) {
        return <QuillSupportTicketsLoadError onRetry={() => loadTickets(false)} />
    }

    return (
        <Card size="sm" flush className="min-w-0 pt-0">
            <div
                // Rows stay clickable while a background refresh is in flight.
                className={cn('min-w-0 transition-opacity', ticketsLoading && 'opacity-60')}
                aria-busy={ticketsLoading}
            >
                <DataTable
                    columns={columns}
                    data={tickets}
                    fullWidth
                    size="sm"
                    getRowId={getTicketId}
                    selectable
                    rowSelection={rowSelection}
                    onRowSelectionChange={(next) => setSelectedTicketIds(Object.keys(next).filter((id) => next[id]))}
                    rowSelectionLabel={(ticket) => `Select ticket ${ticket.ticket_number}`}
                    onRowClick={onRowClick}
                    rowClassName={unreadRowClassName}
                    empty={empty}
                    sorting={tableSorting}
                    onSortingChange={([sort]) => {
                        if (sort) {
                            setSorting({ columnKey: sort.id, order: sort.desc ? -1 : 1 })
                        }
                    }}
                />
            </div>
            {/* A bulk update can empty a later page, so the pager stays to lead back. */}
            {pageCount > 1 && (
                <QuillTablePagination
                    currentPage={currentPage}
                    pageCount={pageCount}
                    pageSize={SUPPORT_TICKETS_PAGE_SIZE}
                    total={totalCount}
                    onPageChange={setCurrentPage}
                />
            )}
        </Card>
    )
}
