import { useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonSkeleton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'

import { SupportTicketApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountSupportTicketsLogic, NOT_LOADED } from './accountSupportTicketsLogic'
import { AccountsEvents } from './constants'

// Matches the Relationships tab, the other client-side-paginated account tab.
const PAGE_SIZE = 10

function SupportTicketsEmptyState({ title, detail }: { title: string; detail: string }): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <BigLeaguesHog className="w-24 h-24" />
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary max-w-sm mb-0">{detail}</p>
        </div>
    )
}

const columns: LemonTableColumns<SupportTicketApi> = [
    {
        title: 'Ticket',
        key: 'ticket_number',
        render: (_, ticket) => (
            <Link
                to={ticket.deep_link}
                target="_blank"
                onClick={() => posthog.capture(AccountsEvents.SupportTicketClicked)}
            >
                #{ticket.ticket_number}
            </Link>
        ),
        sorter: (a, b) => a.ticket_number - b.ticket_number,
    },
    {
        title: 'Last message',
        key: 'last_message_text',
        render: (_, ticket) =>
            ticket.last_message_text ? (
                <span className="line-clamp-1">{ticket.last_message_text}</span>
            ) : (
                <span className="text-muted">—</span>
            ),
    },
    {
        title: 'Status',
        key: 'status',
        render: (_, ticket) => (
            <LemonTag type={ticket.status === 'resolved' ? 'success' : ticket.status === 'new' ? 'primary' : 'default'}>
                {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
            </LemonTag>
        ),
        sorter: (a, b) => a.status.localeCompare(b.status),
    },
    {
        title: 'Last activity',
        key: 'last_message_at',
        render: (_, ticket) =>
            ticket.last_message_at ? <TZLabel time={ticket.last_message_at} /> : <span className="text-muted">—</span>,
        sorter: (a, b) => (a.last_message_at ?? '').localeCompare(b.last_message_at ?? ''),
    },
]

export function AccountSupportTicketsExpansion({ accountId }: { accountId: string }): JSX.Element {
    const { ticketsResult, ticketsResultLoading } = useValues(accountSupportTicketsLogic({ accountId }))

    if (ticketsResultLoading || ticketsResult === NOT_LOADED) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    const { tickets, loadFailed } = ticketsResult

    if (loadFailed) {
        return (
            <SupportTicketsEmptyState
                title="Couldn't load support tickets"
                detail="Something went wrong loading this account's tickets. Try refreshing the page."
            />
        )
    }

    if (!tickets || tickets.length === 0) {
        return (
            <SupportTicketsEmptyState
                title="No support tickets yet"
                detail="Tickets from Slack, email, and the support widget for this account will show up here."
            />
        )
    }

    return (
        <LemonTable<SupportTicketApi>
            size="small"
            embedded
            dataSource={tickets}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: PAGE_SIZE, useUrl: false }}
        />
    )
}
