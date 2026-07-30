import { LemonTableColumn, LemonTableColumns } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { Ticket } from '../../types'
import { TicketGroup, ticketGroupLabel } from './ticketGroups'

type TicketColumn = LemonTableColumn<Ticket, keyof Ticket | undefined>
export type TicketListColumn = LemonTableColumn<TicketListRow, undefined>

/** A synthetic full-width divider row shown above each ticket group.
 *  `empty` marks groups that provably have no tickets matching the current
 *  filters; `count` is the group's filtered total across all pages
 *  (server-provided). */
export interface TicketGroupHeaderRow {
    ticketGroupHeader: string
    empty?: boolean
    count?: number
}

/** What the tickets table renders while grouped: tickets interleaved with
 *  ticket group headers. Mirrors DataTable's `DataTableRow`
 *  label-row pattern (frontend/src/queries/nodes/DataTable). */
export type TicketListRow = Ticket | TicketGroupHeaderRow

export function isTicketGroupHeaderRow(row: TicketListRow): row is TicketGroupHeaderRow {
    return 'ticketGroupHeader' in row
}

interface TicketGroupingContext {
    /** The ordered groups the rows were server-sorted against (the team's
     *  configured groups, or the default). */
    groups: TicketGroup[]
    desc: boolean
    /** Emptiness is only provable where the server-sorted sequence is known to
     *  be complete: before the first group on page 1, after the last group on
     *  the final page, and in gaps between groups adjacent on the same page. */
    isFirstPage: boolean
    isLastPage: boolean
    /** Whole-result-set count per group rank (the API's
     *  `ticket_group_counts`); groups absent from the map matched zero
     *  tickets. */
    counts?: Record<string, number> | null
}

/** Interleave a header above each run of same-group tickets, plus headers
 *  (with an `empty` marker) for every configured group that provably has no
 *  matching tickets. Assumes `tickets` is ticket-group-ordered. */
export function buildTicketGroupedRows(tickets: Ticket[], context: TicketGroupingContext): TicketListRow[] {
    if (tickets.length === 0) {
        return []
    }
    const { groups, desc, isFirstPage, isLastPage, counts } = context
    const ladder = groups.map((group) => group.label)
    const rankByLabel = new Map(ladder.map((label, rank) => [label, rank]))
    if (desc) {
        ladder.reverse()
    }
    const header = (label: string, empty?: boolean): TicketGroupHeaderRow => {
        const row: TicketGroupHeaderRow = { ticketGroupHeader: label }
        if (empty) {
            row.empty = true
        }
        if (counts) {
            row.count = counts[String(rankByLabel.get(label))] ?? 0
        }
        return row
    }
    const rows: TicketListRow[] = []
    let ladderIndex = 0
    let currentGroup: string | null = null
    // One anchor for the whole walk, so a relative date filter can't flip
    // between tickets mid-walk.
    const now = dayjs()

    const emitEmptiesUpTo = (group: string, provable: boolean): void => {
        while (ladderIndex < ladder.length && ladder[ladderIndex] !== group) {
            if (provable) {
                rows.push(header(ladder[ladderIndex], true))
            }
            ladderIndex++
        }
    }

    for (const ticket of tickets) {
        const group = ticketGroupLabel(ticket, groups, now)
        if (group !== currentGroup) {
            // Gaps before the page's first group are provable only on page 1;
            // gaps between groups adjacent on this page are always provable.
            emitEmptiesUpTo(group, currentGroup !== null || isFirstPage)
            rows.push(header(group))
            ladderIndex++ // past the populated group
            currentGroup = group
        }
        rows.push(ticket)
    }
    if (isLastPage) {
        while (ladderIndex < ladder.length) {
            rows.push(header(ladder[ladderIndex], true))
            ladderIndex++
        }
    }
    return rows
}

/** Adapt Ticket columns to the grouped row union: header rows render their
 *  label once, spanning every column (the remaining cells collapse to
 *  colSpan 0); ticket rows delegate to the original renderers untouched. */
export function withTicketGroupHeaderRows(columns: LemonTableColumns<Ticket>): TicketListColumn[] {
    return (columns as TicketColumn[]).map((column, index) => ({
        ...column,
        render: (value: any, row: TicketListRow, recordIndex: number, rowCount: number) => {
            if (isTicketGroupHeaderRow(row)) {
                if (index === 0) {
                    const matchNote =
                        row.empty || row.count === 0
                            ? 'zero tickets match current filters'
                            : row.count !== undefined
                              ? `${row.count} ${row.count === 1 ? 'ticket matches' : 'tickets match'} current filters`
                              : null
                    return {
                        children: (
                            <span className="text-xs font-semibold text-muted-alt">
                                {row.ticketGroupHeader}
                                {matchNote && <span className="ml-2 font-normal text-muted">{matchNote}</span>}
                            </span>
                        ),
                        props: { colSpan: columns.length },
                    }
                }
                return { props: { colSpan: 0 } }
            }
            return column.render ? column.render(value, row, recordIndex, rowCount) : undefined
        },
    })) as TicketListColumn[]
}
