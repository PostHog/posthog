export type TicketStatus = 'open' | 'pending' | 'resolved'
export type TicketChannel = 'widget' | 'slack' | 'email'
export type TicketSlaState = 'on-track' | 'at-risk' | 'breached'

export type ConversationTicket = {
    id: string
    subject: string
    customer: string
    status: TicketStatus
    channel: TicketChannel
    priority: 'low' | 'medium' | 'high'
    aiContained: boolean
    assignedTo: string
    updatedAgoMinutes: number
    slaState: TicketSlaState
}

export const sampleTickets: ConversationTicket[] = [
    {
        id: 'CX-9112',
        subject: 'Widget stuck reconnecting on EU pages',
        customer: 'Keypath',
        status: 'open',
        channel: 'widget',
        priority: 'high',
        aiContained: false,
        assignedTo: 'Dana',
        updatedAgoMinutes: 4,
        slaState: 'at-risk',
    },
    {
        id: 'CX-9108',
        subject: 'Need invoice with PO number',
        customer: 'Northwind',
        status: 'pending',
        channel: 'email',
        priority: 'medium',
        aiContained: true,
        assignedTo: 'Alex',
        updatedAgoMinutes: 12,
        slaState: 'on-track',
    },
    {
        id: 'CX-9105',
        subject: 'Slack bot double posting replies',
        customer: 'Hooli',
        status: 'open',
        channel: 'slack',
        priority: 'high',
        aiContained: false,
        assignedTo: 'Priya',
        updatedAgoMinutes: 26,
        slaState: 'on-track',
    },
    {
        id: 'CX-9101',
        subject: 'Custom refund exception for VIP',
        customer: 'Lightspeed',
        status: 'pending',
        channel: 'widget',
        priority: 'high',
        aiContained: false,
        assignedTo: 'Mei',
        updatedAgoMinutes: 33,
        slaState: 'at-risk',
    },
    {
        id: 'CX-9098',
        subject: 'SAML redirect loop after login',
        customer: 'Acme Corp',
        status: 'open',
        channel: 'email',
        priority: 'high',
        aiContained: false,
        assignedTo: 'Sean',
        updatedAgoMinutes: 41,
        slaState: 'breached',
    },
    {
        id: 'CX-9097',
        subject: 'AI asking wrong escalation contact',
        customer: 'Ramen Club',
        status: 'resolved',
        channel: 'slack',
        priority: 'medium',
        aiContained: true,
        assignedTo: 'Support bot',
        updatedAgoMinutes: 55,
        slaState: 'on-track',
    },
    {
        id: 'CX-9095',
        subject: 'Need sandbox refresh for QA',
        customer: 'Atlas Partners',
        status: 'open',
        channel: 'email',
        priority: 'low',
        aiContained: true,
        assignedTo: 'Leo',
        updatedAgoMinutes: 63,
        slaState: 'on-track',
    },
    {
        id: 'CX-9092',
        subject: 'GDPR request for full transcript',
        customer: 'Orchid',
        status: 'pending',
        channel: 'widget',
        priority: 'medium',
        aiContained: false,
        assignedTo: 'Sam',
        updatedAgoMinutes: 80,
        slaState: 'breached',
    },
    {
        id: 'CX-9088',
        subject: 'Slack connect channel offline',
        customer: 'Novo',
        status: 'open',
        channel: 'slack',
        priority: 'high',
        aiContained: false,
        assignedTo: 'Taylor',
        updatedAgoMinutes: 95,
        slaState: 'at-risk',
    },
    {
        id: 'CX-9082',
        subject: 'AI summary missing attachment links',
        customer: 'Orbit',
        status: 'resolved',
        channel: 'widget',
        priority: 'low',
        aiContained: true,
        assignedTo: 'Support bot',
        updatedAgoMinutes: 140,
        slaState: 'on-track',
    },
]
