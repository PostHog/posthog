import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { ChartAxis, DataVisualizationNode, DateRange, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import type { TicketSlaState, TicketStatus } from '../../types'

export const UNRESOLVED_STATUSES: TicketStatus[] = ['new', 'open', 'pending', 'on_hold']

export interface SupportOverviewNumbers {
    open: number
    unassigned: number
    slaAtRisk: number
    slaBreached: number
    /** Unresolved tickets that have an SLA deadline. Zero means the project does not use SLAs. */
    withSla: number
}

export type SupportOverviewNumberKey = 'open' | 'unassigned' | 'slaAtRisk' | 'slaBreached'

// The SLA windows match the ticket list's `sla` filter, so a card and the list behind it count the same tickets.
export const SUPPORT_OVERVIEW_NUMBERS_QUERY = `
    SELECT
        count() AS open,
        countIf(assignee.user_id IS NULL AND assignee.role_id IS NULL) AS unassigned,
        countIf(sla_due_at >= now() AND sla_due_at <= now() + INTERVAL 1 HOUR) AS sla_at_risk,
        countIf(sla_due_at < now()) AS sla_breached,
        countIf(sla_due_at IS NOT NULL) AS with_sla
    FROM system.support_tickets
    WHERE status != 'resolved'
`

export function parseSupportOverviewNumbers(row: unknown[] | undefined): SupportOverviewNumbers {
    const [open, unassigned, slaAtRisk, slaBreached, withSla] = (row ?? []).map((value) => Number(value) || 0)
    return {
        open: open ?? 0,
        unassigned: unassigned ?? 0,
        slaAtRisk: slaAtRisk ?? 0,
        slaBreached: slaBreached ?? 0,
        withSla: withSla ?? 0,
    }
}

export function ticketListUrl(key: SupportOverviewNumberKey): string {
    const params: { status: TicketStatus[]; assignee?: string; sla?: TicketSlaState; order_by?: string } = {
        status: UNRESOLVED_STATUSES,
    }
    if (key === 'unassigned') {
        params.assignee = 'unassigned'
    }
    if (key === 'slaAtRisk' || key === 'slaBreached') {
        params.sla = key === 'slaAtRisk' ? 'at-risk' : 'breached'
        params.order_by = 'sla_due_at'
    }
    return combineUrl(urls.supportTickets(), params).url
}

// The events table does not apply ticket access control, but system.support_tickets does.
// Each chart joins through it, so a viewer only counts the tickets they can read.
const READABLE_TICKETS_HOGQL = 'properties.ticket_id IN (SELECT toString(id) FROM system.support_tickets)'

// HogQL returns 100 rows by default, which cuts the latest days from a longer range.
const MAX_CHART_DAYS = 3660

// Every chart is a HogQLQuery on purpose. The query cache partitions a HogQLQuery by the viewer's ticket access
// when it reads system.support_tickets. It does not do that for a TrendsQuery with the same filter, so a
// restricted viewer could get an unrestricted viewer's cached result.
function dailyChart(
    query: string,
    dateRange: DateRange,
    display: ChartDisplayType,
    yAxis: ChartAxis
): DataVisualizationNode {
    return {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query, filters: { dateRange } },
        display,
        chartSettings: { xAxis: { column: 'day' }, yAxis: [yAxis] },
    }
}

export function ticketsCreatedQuery(dateRange: DateRange): DataVisualizationNode {
    return dailyChart(
        `
            SELECT toStartOfDay(timestamp) AS day, count() AS tickets_created
            FROM events
            WHERE event = '$conversation_ticket_created'
                AND {filters}
                AND ${READABLE_TICKETS_HOGQL}
            GROUP BY day
            ORDER BY day
            LIMIT ${MAX_CHART_DAYS}
        `,
        dateRange,
        ChartDisplayType.ActionsBar,
        { column: 'tickets_created' }
    )
}

export function ticketsResolvedQuery(dateRange: DateRange): DataVisualizationNode {
    return dailyChart(
        `
            SELECT toStartOfDay(timestamp) AS day, count() AS tickets_resolved
            FROM events
            WHERE event = '$conversation_ticket_status_changed'
                AND properties.new_status = 'resolved'
                AND {filters}
                AND ${READABLE_TICKETS_HOGQL}
            GROUP BY day
            ORDER BY day
            LIMIT ${MAX_CHART_DAYS}
        `,
        dateRange,
        ChartDisplayType.ActionsBar,
        { column: 'tickets_resolved' }
    )
}

export function slaAttainmentQuery(dateRange: DateRange): DataVisualizationNode {
    // Replies on tickets without an SLA stay out of both sides of the ratio.
    return dailyChart(
        `
            SELECT
                toStartOfDay(timestamp) AS day,
                round(100 * countIf(properties.sla_breached = false) / count(), 1) AS replies_within_sla
            FROM events
            WHERE event = '$conversation_message_sent'
                AND properties.sla_active = true
                AND {filters}
                AND ${READABLE_TICKETS_HOGQL}
            GROUP BY day
            ORDER BY day
            LIMIT ${MAX_CHART_DAYS}
        `,
        dateRange,
        ChartDisplayType.ActionsLineGraph,
        { column: 'replies_within_sla', settings: { formatting: { suffix: '%' } } }
    )
}

export function firstResponseTimeQuery(dateRange: DateRange): DataVisualizationNode {
    // The range bounds the ticket creation time only. A reply sent after the range end still counts,
    // so slow first responses stay in the median.
    return dailyChart(
        `
            SELECT
                toStartOfDay(created_at) AS day,
                round(median(dateDiff('second', created_at, first_reply_at)) / 3600, 2) AS median_hours
            FROM (
                SELECT
                    properties.ticket_id AS ticket_id,
                    minIf(timestamp, event = '$conversation_ticket_created') AS created_at,
                    minIf(timestamp, event = '$conversation_message_sent') AS first_reply_at
                FROM events
                WHERE event IN ('$conversation_ticket_created', '$conversation_message_sent')
                    AND timestamp >= {filters.dateRange.from}
                    AND properties.ticket_id IN (
                        SELECT properties.ticket_id
                        FROM events
                        WHERE event = '$conversation_ticket_created'
                            AND {filters}
                            AND ${READABLE_TICKETS_HOGQL}
                    )
                GROUP BY ticket_id
                HAVING countIf(event = '$conversation_ticket_created') > 0
                    AND countIf(event = '$conversation_message_sent') > 0
                    AND first_reply_at >= created_at
            )
            GROUP BY day
            ORDER BY day
            LIMIT ${MAX_CHART_DAYS}
        `,
        dateRange,
        ChartDisplayType.ActionsLineGraph,
        { column: 'median_hours', settings: { formatting: { suffix: ' h' } } }
    )
}
