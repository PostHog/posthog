import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import {
    DataVisualizationNode,
    DateRange,
    InsightVizNode,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, HogQLMathType, PropertyFilterType, PropertyOperator } from '~/types'

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
        countIf(status != 'resolved') AS open,
        countIf(status != 'resolved' AND assignee.user_id IS NULL AND assignee.role_id IS NULL) AS unassigned,
        countIf(status != 'resolved' AND sla_due_at >= now() AND sla_due_at <= now() + INTERVAL 1 HOUR) AS sla_at_risk,
        countIf(status != 'resolved' AND sla_due_at < now()) AS sla_breached,
        countIf(status != 'resolved' AND sla_due_at IS NOT NULL) AS with_sla
    FROM system.support_tickets
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

function trendsViz(source: TrendsQuery): InsightVizNode {
    return { kind: NodeKind.InsightVizNode, source }
}

export function ticketsCreatedQuery(dateRange: DateRange): InsightVizNode {
    return trendsViz({
        kind: NodeKind.TrendsQuery,
        dateRange,
        interval: 'day',
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$conversation_ticket_created',
                custom_name: 'Tickets created',
                math: BaseMathType.TotalCount,
            },
        ],
        breakdownFilter: { breakdown: 'channel_source', breakdown_type: 'event' },
        trendsFilter: { display: ChartDisplayType.ActionsBar, showLegend: true },
    })
}

export function ticketsResolvedQuery(dateRange: DateRange): InsightVizNode {
    return trendsViz({
        kind: NodeKind.TrendsQuery,
        dateRange,
        interval: 'day',
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$conversation_ticket_status_changed',
                custom_name: 'Tickets resolved',
                math: BaseMathType.TotalCount,
                properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: 'new_status',
                        operator: PropertyOperator.Exact,
                        value: 'resolved',
                    },
                ],
            },
        ],
        trendsFilter: { display: ChartDisplayType.ActionsBar },
    })
}

export function slaAttainmentQuery(dateRange: DateRange): InsightVizNode {
    return trendsViz({
        kind: NodeKind.TrendsQuery,
        dateRange,
        interval: 'day',
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$conversation_message_sent',
                custom_name: 'Replies within SLA',
                math: HogQLMathType.HogQL,
                // Replies on tickets without an SLA stay out of both sides of the ratio.
                math_hogql:
                    'round(100 * countIf(properties.sla_active = true AND properties.sla_breached = false) / nullIf(countIf(properties.sla_active = true), 0), 1)',
            },
        ],
        trendsFilter: { display: ChartDisplayType.ActionsLineGraph, aggregationAxisPostfix: '%' },
    })
}

export function firstResponseTimeQuery(dateRange: DateRange): DataVisualizationNode {
    return {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: `
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
                        AND {filters}
                    GROUP BY ticket_id
                    HAVING countIf(event = '$conversation_ticket_created') > 0
                        AND countIf(event = '$conversation_message_sent') > 0
                        AND first_reply_at >= created_at
                )
                GROUP BY day
                ORDER BY day
            `,
            filters: { dateRange },
        },
        display: ChartDisplayType.ActionsLineGraph,
        chartSettings: {
            xAxis: { column: 'day' },
            yAxis: [{ column: 'median_hours', settings: { formatting: { suffix: ' h' } } }],
        },
    }
}
