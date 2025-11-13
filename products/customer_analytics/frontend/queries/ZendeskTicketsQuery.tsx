import { Link } from '@posthog/lemon-ui'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'
import { hogql } from '~/queries/utils'

const DEFAULT_COLUMN_CONFIG: QueryContextColumn = {
    width: '60px',
    align: 'center',
}

const ZENDESK_TICKETS_QUERY_COLUMNS = ['id', 'url', 'subject', 'status', 'priority', 'created_at', 'updated_at']

interface ZendeskTicketsQueryProps {
    personId: string
    status?: string
    priority?: string
    orderBy?: string
    orderDirection?: string
}

export const zendeskTicketsQuery = ({
    personId,
    status,
    priority,
    orderBy,
    orderDirection,
}: ZendeskTicketsQueryProps): DataTableNode => {
    const conditions: string[] = ['1=1']
    if (status && status !== 'all') {
        conditions.push(`status = '${status}'`)
    }
    if (priority && priority !== 'all') {
        conditions.push(`priority = '${priority}'`)
    }

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
                )
            select tickets.id, url, subject, status, priority, created_at, updated_at
            from tickets
            inner join zendesk_user on zendesk_user.id = tickets.requester_id
            where ${hogql.raw(conditions.join(' AND '))}
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

export const useZendeskTicketsQueryContext = (): QueryContext => {
    return {
        columns: {
            id: DEFAULT_COLUMN_CONFIG,
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
                        <Link to={url} target="_new" className="truncate">
                            {row[subjectIndex]}
                        </Link>
                    )
                },
                width: '400px',
            },
        },
        emptyStateHeading: 'There are no matching tickets for this customer',
        emptyStateDetail: 'They have not submitted any support tickets yet',
    }
}
