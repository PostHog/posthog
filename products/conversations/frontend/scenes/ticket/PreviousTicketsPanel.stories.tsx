import type { Meta, StoryObj } from '@storybook/react'

import type { Ticket, TicketStatus } from '../../types'
import { PreviousTicketsPanel } from './PreviousTicketsPanel'

// The panel a support teammate reads on a ticket to see what else the requester has sent.
// It stays collapsed by default, so the header has to say whether anything in it is still live.

const meta: Meta<typeof PreviousTicketsPanel> = {
    title: 'Scenes-App/Support/PreviousTicketsPanel',
    component: PreviousTicketsPanel,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-08-06' },
}
export default meta

type Story = StoryObj<typeof PreviousTicketsPanel>

function makeTicket(ticketNumber: number, status: TicketStatus, lastMessageText: string): Ticket {
    return {
        id: `ticket-${ticketNumber}`,
        ticket_number: ticketNumber,
        distinct_id: 'someone@example.com',
        status,
        channel_source: 'email',
        anonymous_traits: {},
        identity_verified: true,
        ai_resolved: false,
        created_at: '2026-07-28T09:12:00Z',
        updated_at: '2026-08-04T11:40:00Z',
        message_count: 3,
        last_message_at: '2026-08-04T11:40:00Z',
        last_message_text: lastMessageText,
        unread_team_count: 0,
        unread_customer_count: 0,
    } as Ticket
}

const HISTORY: Ticket[] = [
    makeTicket(1189, 'open', 'Still cannot export the funnel to CSV'),
    makeTicket(1174, 'pending', 'Waiting on the sandbox environment'),
    makeTicket(1102, 'resolved', 'Invoice for January looked wrong'),
    makeTicket(1064, 'resolved', 'How do I invite a teammate?'),
    makeTicket(1041, 'resolved', 'Session replay missing on mobile'),
]

function Sidebar({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="max-w-sm">{children}</div>
}

export const SomeStillOpen: Story = {
    render: () => (
        <Sidebar>
            <PreviousTicketsPanel previousTickets={HISTORY} openCount={2} />
        </Sidebar>
    ),
}

export const AllResolved: Story = {
    render: () => (
        <Sidebar>
            <PreviousTicketsPanel previousTickets={HISTORY.filter((t) => t.status === 'resolved')} openCount={0} />
        </Sidebar>
    ),
}

export const NoHistory: Story = {
    render: () => (
        <Sidebar>
            <PreviousTicketsPanel previousTickets={[]} openCount={0} />
        </Sidebar>
    ),
}
