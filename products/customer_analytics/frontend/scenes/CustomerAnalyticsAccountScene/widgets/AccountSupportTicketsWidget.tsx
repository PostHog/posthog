import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconSupport } from '@posthog/icons'
import { LemonSkeleton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import {
    accountSupportTicketsLogic,
    NOT_LOADED,
} from 'products/customer_analytics/frontend/components/Accounts/accountSupportTicketsLogic'
import { AccountsEvents } from 'products/customer_analytics/frontend/components/Accounts/constants'
import type { SupportTicketApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountWidgetCard } from './AccountWidgetCard'

const PAGE_SIZE = 5

interface AccountSupportTicketsWidgetProps {
    accountId: string
    onRemove?: () => void
}

const columns: LemonTableColumns<SupportTicketApi> = [
    {
        title: 'Ticket',
        key: 'ticket_number',
        width: 0,
        render: (_, ticket) => (
            <Link
                to={ticket.deep_link}
                target="_blank"
                onClick={() => posthog.capture(AccountsEvents.SupportTicketClicked)}
            >
                #{ticket.ticket_number}
            </Link>
        ),
    },
    {
        title: 'Last message',
        key: 'last_message_text',
        render: (_, ticket) =>
            ticket.last_message_text ? (
                <span className="line-clamp-1 text-secondary">{ticket.last_message_text}</span>
            ) : (
                <span className="text-muted">—</span>
            ),
    },
    {
        title: 'Status',
        key: 'status',
        width: 0,
        render: (_, ticket) => (
            <LemonTag
                size="small"
                type={ticket.status === 'resolved' ? 'success' : ticket.status === 'new' ? 'primary' : 'default'}
            >
                {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
            </LemonTag>
        ),
    },
    {
        title: 'Activity',
        key: 'last_message_at',
        align: 'right',
        width: 0,
        render: (_, ticket) =>
            ticket.last_message_at ? (
                <span className="text-secondary whitespace-nowrap">
                    <TZLabel time={ticket.last_message_at} />
                </span>
            ) : (
                <span className="text-muted">—</span>
            ),
    },
]

function isOpenTicket(ticket: SupportTicketApi): boolean {
    return ticket.status !== 'resolved' && ticket.status !== 'closed'
}

export function AccountSupportTicketsWidget({ accountId, onRemove }: AccountSupportTicketsWidgetProps): JSX.Element {
    const logic = accountSupportTicketsLogic({ accountId })
    const { ticketsResult, ticketsResultLoading } = useValues(logic)
    const { loadTickets } = useActions(logic)

    const tickets = ticketsResult.tickets ?? []
    const openCount = tickets.filter(isOpenTicket).length

    let body: JSX.Element
    if (ticketsResult === NOT_LOADED) {
        body = <LemonSkeleton className="h-32 w-full m-3" />
    } else if (ticketsResult.loadFailed) {
        body = (
            <p className="text-sm text-secondary p-3 mb-0">Couldn't load support tickets. Try refreshing the page.</p>
        )
    } else if (tickets.length === 0) {
        body = (
            <p className="text-sm text-secondary p-3 mb-0">
                No support tickets yet. Tickets from Slack, email, and the support widget will show up here.
            </p>
        )
    } else {
        body = (
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

    return (
        <AccountWidgetCard
            icon={<IconSupport />}
            title="Support tickets"
            meta={ticketsResult !== NOT_LOADED && !ticketsResult.loadFailed ? <span>{openCount} open</span> : null}
            onRefresh={ticketsResultLoading ? undefined : loadTickets}
            onRemove={onRemove}
            data-attr="account-support-tickets-widget"
        >
            {body}
        </AccountWidgetCard>
    )
}
