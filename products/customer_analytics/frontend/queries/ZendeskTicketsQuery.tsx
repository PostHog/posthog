import { Link } from '@posthog/lemon-ui'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'

const DEFAULT_COLUMN_CONFIG = {
    width: '60px',
    align: 'center',
} as QueryContextColumn

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
            query: `
              with
                person as (
                    select properties.email as email
                    from persons
                    where id = '${personId}'
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
            where ${conditions.join(' AND ')}
            order by tickets.${orderBy || 'updated_at'} ${orderDirection || 'asc'}
            limit 500
            `,
        },
        showTimings: false,
        showOpenEditorButton: false,
        hiddenColumns: ['url'],
        columns: ['id', 'url', 'subject', 'status', 'priority', 'created_at', 'updated_at'],
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
                render: ({ query, record, columnName }) => {
                    const subjectIndex = query.columns.indexOf(columnName)
                    const urlIndex = query.columns.indexOf('url')
                    const url = record[urlIndex].replace('/api/v2', '').replace('.json', '')
                    return (
                        <Link to={url} target="_new" className="truncate">
                            {record[subjectIndex]}
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
