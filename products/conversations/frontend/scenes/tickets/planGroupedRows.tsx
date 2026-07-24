import { LemonTableColumn, LemonTableColumns } from '@posthog/lemon-ui'

import { Ticket } from '../../types'
import { PLAN_GROUPS, planLabel, planRank } from './planTags'

type TicketColumn = LemonTableColumn<Ticket, keyof Ticket | undefined>
export type TicketListColumn = LemonTableColumn<TicketListRow, undefined>

/** A synthetic full-width divider row shown above each plan group. `empty`
 *  marks groups that provably have no tickets matching the current filters;
 *  `count` is the group's filtered total across all pages (server-provided). */
export interface PlanHeaderRow {
    planHeader: string
    empty?: boolean
    count?: number
}

/** What the tickets table renders while grouped: tickets interleaved with
 *  plan-group headers. Mirrors DataTable's `DataTableRow` label-row pattern
 *  (frontend/src/queries/nodes/DataTable). */
export type TicketListRow = Ticket | PlanHeaderRow

export function isPlanHeaderRow(row: TicketListRow): row is PlanHeaderRow {
    return 'planHeader' in row
}

/** Whether the page's tickets really are in plan-rank order (the server's
 *  `order_by=plan`/`-plan` contract). While a sort change is in flight, the
 *  sorting state says "plan" but `tickets` still holds the previous ordering —
 *  grouping THAT would emit duplicate headers (and duplicate row keys), so the
 *  scene only groups once this holds. */
export function isPlanOrdered(tickets: Ticket[], desc: boolean): boolean {
    for (let i = 1; i < tickets.length; i++) {
        const prev = planRank(tickets[i - 1].tags)
        const next = planRank(tickets[i].tags)
        if (desc ? next > prev : next < prev) {
            return false
        }
    }
    return true
}

interface PlanGroupingContext {
    desc: boolean
    /** Emptiness is only provable where the server-sorted sequence is known to
     *  be complete: before the first group on page 1, after the last group on
     *  the final page, and in gaps between groups adjacent on the same page. */
    isFirstPage: boolean
    isLastPage: boolean
    /** Whole-result-set count per plan rank (the API's `plan_counts`); groups
     *  absent from the map matched zero tickets. */
    counts?: Record<string, number> | null
}

/** Interleave a header above each run of same-plan tickets, plus headers (with
 *  an `empty` marker) for every ladder group that provably has no matching
 *  tickets. Assumes `tickets` is plan-ordered — see isPlanOrdered. */
export function buildPlanGroupedRows(tickets: Ticket[], context: PlanGroupingContext): TicketListRow[] {
    if (tickets.length === 0) {
        return []
    }
    const { desc, isFirstPage, isLastPage, counts } = context
    const ladder = PLAN_GROUPS.map((group) => group.label)
    const rankByLabel = new Map(ladder.map((label, rank) => [label, rank]))
    if (desc) {
        ladder.reverse()
    }
    const header = (label: string, empty?: boolean): PlanHeaderRow => {
        const row: PlanHeaderRow = { planHeader: label }
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

    const emitEmptiesUpTo = (group: string, provable: boolean): void => {
        while (ladderIndex < ladder.length && ladder[ladderIndex] !== group) {
            if (provable) {
                rows.push(header(ladder[ladderIndex], true))
            }
            ladderIndex++
        }
    }

    for (const ticket of tickets) {
        const group = planLabel(ticket.tags)
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
export function withPlanHeaderRows(columns: LemonTableColumns<Ticket>): TicketListColumn[] {
    return (columns as TicketColumn[]).map((column, index) => ({
        ...column,
        render: (value: any, row: TicketListRow, recordIndex: number, rowCount: number) => {
            if (isPlanHeaderRow(row)) {
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
                                {row.planHeader}
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
