export type TicketSummary = {
    id: string
    subject: string
    customer: string
    minutesOpen: number
    channel: 'widget' | 'slack' | 'email'
}

export type TicketPod = {
    key: string
    title: string
    description: string
    targetUrl: string
    tickets: TicketSummary[]
}

const sampleTickets: TicketSummary[] = [
    {
        id: 'CX-9110',
        subject: 'Chat widget not loading on marketing pages',
        customer: 'Keypath',
        minutesOpen: 15,
        channel: 'widget',
    },
    {
        id: 'CX-9107',
        subject: 'Slack sync missing replies',
        customer: 'Ramen Club',
        minutesOpen: 21,
        channel: 'slack',
    },
    {
        id: 'CX-9103',
        subject: 'Need SOC2 letter for procurement',
        customer: 'Northwind',
        minutesOpen: 29,
        channel: 'email',
    },
    {
        id: 'CX-9099',
        subject: 'AI escalated due to custom refund policy',
        customer: 'Orchid',
        minutesOpen: 36,
        channel: 'widget',
    },
    {
        id: 'CX-9090',
        subject: 'Priority deal stuck awaiting rep',
        customer: 'Acme Corp',
        minutesOpen: 49,
        channel: 'slack',
    },
    {
        id: 'CX-9086',
        subject: 'Partner requesting sandbox reset',
        customer: 'Atlas Partners',
        minutesOpen: 58,
        channel: 'email',
    },
]

export const ticketPods: TicketPod[] = [
    {
        key: 'recent-escalations',
        title: 'Last 10 escalated',
        description: 'AI fallbacks that still need a human response',
        targetUrl: '/conversations/tickets?view=escalated',
        tickets: sampleTickets.slice(0, 3),
    },
    {
        key: 'sla-breach-risk',
        title: 'SLA breach risk',
        description: 'Tickets within 15 minutes of SLA promise',
        targetUrl: '/conversations/tickets?view=sla-risk',
        tickets: sampleTickets.slice(3, 5),
    },
    {
        key: 'awaiting-reply',
        title: 'Awaiting reply',
        description: 'Customers waiting on us for more than 20 minutes',
        targetUrl: '/conversations/tickets?view=awaiting-reply',
        tickets: sampleTickets.slice(5),
    },
]
