import { Link } from '@posthog/lemon-ui'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'
import { hogql } from '~/queries/utils'

const DEFAULT_COLUMN_CONFIG: QueryContextColumn = {
    width: '60px',
    align: 'center',
}

const ZENDESK_TICKETS_QUERY_COLUMNS = ['id', 'url', 'subject', 'status', 'priority', 'created_at', 'updated_at']

interface BaseZendeskTicketsQueryProps {
    status?: string
    priority?: string
    orderBy?: string
    orderDirection?: string
}

interface ZendeskPersonTicketsQueryProps extends BaseZendeskTicketsQueryProps {
    personId: string
}

export const zendeskPersonTicketsQuery = ({
    personId,
    status,
    priority,
    orderBy,
    orderDirection,
}: ZendeskPersonTicketsQueryProps): DataTableNode => {
    const statusFilter = status || 'all'
    const priorityFilter = priority || 'all'

    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: hogql`
              with
                person as (
                    select properties.email as email
                    from persons
                    where id = ${personId}
                ),
                zendesk_user as (
                    select u.id, u.email
                    from zendesk_users u
                    inner join person p on p.email = u.email
                ),
                tickets as (
                    select *
                    from zendesk_tickets
                    where (${statusFilter} = 'all' OR status = ${statusFilter})
                      AND (${priorityFilter} = 'all' OR priority = ${priorityFilter})
                )
            select tickets.id, url, subject, status, priority, created_at, updated_at
            from tickets
            inner join zendesk_user on zendesk_user.id = tickets.requester_id
            order by tickets.${hogql.identifier(orderBy || 'updated_at')} ${hogql.identifier(orderDirection || 'asc')}
            limit 500
            `,
        },
        showTimings: false,
        showOpenEditorButton: false,
        hiddenColumns: ['url'],
        columns: ZENDESK_TICKETS_QUERY_COLUMNS,
    }
}

interface ZendeskGroupTicketsQueryProps extends BaseZendeskTicketsQueryProps {
    groupKey: string
}

export const zendeskGroupTicketsQuery = ({
    groupKey,
    status,
    priority,
    orderBy,
    orderDirection,
}: ZendeskGroupTicketsQueryProps): DataTableNode => {
    const statusFilter = status || 'all'
    const priorityFilter = priority || 'all'

    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: hogql`
            select t.id, t.url, t.subject, t.status, t.priority, t.created_at as created_at, t.updated_at as updated_at
            from zendesk_organizations o
            inner join zendesk_tickets t on o.id = t.organization_id
            where o.external_id = ${groupKey}
              AND (${statusFilter} = 'all' OR t.status = ${statusFilter})
              AND (${priorityFilter} = 'all' OR t.priority = ${priorityFilter})
            order by t.${hogql.identifier(orderBy || 'updated_at')} ${hogql.identifier(orderDirection || 'asc')}
            limit 500
            `,
        },
        showTimings: false,
        showOpenEditorButton: false,
        hiddenColumns: ['url'],
        columns: ZENDESK_TICKETS_QUERY_COLUMNS,
    }
}

export const useZendeskTicketsQueryContext = (): QueryContext => {
    return {
        columns: {
            id: { ...DEFAULT_COLUMN_CONFIG, render: ({ value }) => <span className="ph-no-capture">{value}</span> },
            status: DEFAULT_COLUMN_CONFIG,
            priority: DEFAULT_COLUMN_CONFIG,
            created_at: { ...DEFAULT_COLUMN_CONFIG, title: 'created' },
            updated_at: { ...DEFAULT_COLUMN_CONFIG, title: 'updated' },
            subject: {
                render: ({ record, columnName }) => {
                    const row = record as (number | string)[]
                    const subjectIndex = ZENDESK_TICKETS_QUERY_COLUMNS.indexOf(columnName)
                    const urlIndex = ZENDESK_TICKETS_QUERY_COLUMNS.indexOf('url')
                    const url = (row[urlIndex] as string).replace('/api/v2', '').replace('.json', '')
                    return (
                        <span className="ph-no-capture">
                            <Link to={url} target="_new" className="truncate">
                                {row[subjectIndex]}
                            </Link>
                        </span>
                    )
                },
                width: '400px',
            },
        },
        emptyStateHeading: 'There are no matching tickets for this customer',
        emptyStateDetail: 'They have not submitted any support tickets yet',
    }
}
