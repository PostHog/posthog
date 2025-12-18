export type TicketStatus = 'new' | 'open' | 'pending' | 'on_hold' | 'resolved'
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
        status: 'new',
        channel: 'widget',
        priority: 'high',
        aiContained: false,
        assignedTo: 'Unassigned',
        updatedAgoMinutes: 2,
        slaState: 'on-track',
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
        status: 'on_hold',
        channel: 'slack',
        priority: 'medium',
        aiContained: true,
        assignedTo: 'Mei',
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

export type EscalationTicket = {
    id: string
    subject: string
    reason: string
    channel: TicketChannel
    owner: string
    minutesOpen: number
}

export const escalationTickets: EscalationTicket[] = [
    {
        id: 'CX-9102',
        subject: 'EU checkout flow failing on step 2',
        reason: 'Payment policy exception',
        channel: 'widget',
        owner: '',
        minutesOpen: 48,
    },
    {
        id: 'CX-9096',
        subject: 'API throttling for Tier X accounts',
        reason: 'Exceeded AI policy guardrail',
        channel: 'slack',
        owner: '',
        minutesOpen: 73,
    },
    {
        id: 'CX-9094',
        subject: 'Invoice download button missing',
        reason: 'High-value customer (ARR > $250k)',
        channel: 'email',
        owner: '',
        minutesOpen: 95,
    },
    {
        id: 'CX-9089',
        subject: 'SAML login loop detected',
        reason: 'Security escalation rule',
        channel: 'widget',
        owner: '',
        minutesOpen: 115,
    },
]

export type TicketSummary = {
    id: string
    subject: string
    customer: string
    minutesOpen: number
    channel: TicketChannel
}

export type TicketPod = {
    key: string
    title: string
    description: string
    targetUrl: string
    tickets: TicketSummary[]
}

const ticketPodSampleTickets: TicketSummary[] = [
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
        tickets: ticketPodSampleTickets.slice(0, 3),
    },
    {
        key: 'sla-breach-risk',
        title: 'SLA breach risk',
        description: 'Tickets within 15 minutes of SLA promise',
        targetUrl: '/conversations/tickets?view=sla-risk',
        tickets: ticketPodSampleTickets.slice(3, 5),
    },
    {
        key: 'awaiting-reply',
        title: 'Awaiting reply',
        description: 'Customers waiting on us for more than 20 minutes',
        targetUrl: '/conversations/tickets?view=awaiting-reply',
        tickets: ticketPodSampleTickets.slice(5),
    },
]

export type ConversationMessage = {
    id: string
    actor: 'customer' | 'ai' | 'human'
    author: string
    role?: string
    timestamp: string
    content: string
    attachments?: { name: string; url: string }[]
}

export type TicketDetail = {
    id: string
    subject: string
    status: TicketStatus
    priority: 'low' | 'medium' | 'high'
    channel: TicketChannel
    createdAt: string
    updatedAt: string
    aiContainment: boolean
    assignedTo: string
    queue: string
    customer: {
        name: string
        company: string
        plan: string
        region: string
        mrr: string
        tags: string[]
    }
    timeline: ConversationMessage[]
    aiInsights: {
        summary: string
        fallbackReason: string
        referencedContent: string[]
        suggestedReply: string
    }
    recentEvents: { id: string; description: string; ts: string }[]
    sessionRecording: { id: string; url: string; duration: string }
    sla: {
        policy: string
        promise: string
        timeRemaining: string
        risk: TicketSlaState
    }
}

export const ticketDetail: TicketDetail = {
    id: 'CX-9112',
    subject: 'Widget stuck reconnecting on EU pricing page',
    status: 'open',
    priority: 'high',
    channel: 'widget',
    createdAt: 'Today • 08:14 UTC',
    updatedAt: 'Today • 09:01 UTC',
    aiContainment: false,
    assignedTo: 'Dana Hill',
    queue: 'Tier 2 · EMEA',
    customer: {
        name: 'Sasha Levin',
        company: 'Keypath Retail',
        plan: 'Enterprise',
        region: 'Berlin, Germany',
        mrr: '$420k ARR',
        tags: ['EU', 'High ARR', 'Contracts'],
    },
    timeline: [
        {
            id: 'msg-1',
            actor: 'customer',
            author: 'Sasha (customer)',
            timestamp: '08:14',
            content: 'Hi! Our embedded chat widget on the /pricing page keeps reconnecting every ~20 seconds.',
            attachments: [{ name: 'console-log.txt', url: '#' }],
        },
        {
            id: 'msg-2',
            actor: 'ai',
            author: 'Conversations AI',
            timestamp: '08:15',
            content:
                'Thanks Sasha! I pulled the latest deploy logs and it looks like CSP changed last night. Can you confirm if your marketing team updated the page?',
        },
        {
            id: 'msg-3',
            actor: 'customer',
            author: 'Sasha (customer)',
            timestamp: '08:17',
            content:
                'Marketing confirmed no changes. We did roll out a new Cloudflare rule though. Can you help verify our allowlist?',
        },
        {
            id: 'msg-4',
            actor: 'ai',
            author: 'Conversations AI',
            timestamp: '08:18',
            content:
                'Cloudflare rule 443-block-bot is blocking *.posthog.com websocket connections. I can walk you through updating it.',
        },
        {
            id: 'msg-5',
            actor: 'customer',
            author: 'Sasha (customer)',
            timestamp: '08:20',
            content: 'Please loop in your team. This is affecting a paid launch campaign.',
        },
        {
            id: 'msg-6',
            actor: 'human',
            author: 'Dana Hill',
            role: 'Support engineer',
            timestamp: '08:28',
            content:
                'Jumping in! I’ll review the Cloudflare config and share the allowlist snippet. In the meantime the campaign traffic is temporarily routed to an unaffected edge.',
        },
    ],
    aiInsights: {
        summary:
            'AI detected websocket disconnects caused by a new Cloudflare rule. Escalated to human because enterprise campaign flagged as high priority.',
        fallbackReason: 'Priority account policy requires human confirmation for network changes.',
        referencedContent: ['Procedures · Cloudflare allowlist', 'Article · Widget troubleshooting checklist'],
        suggestedReply:
            'Hi Sasha! I reviewed the firewall logs and the new rule 443-block-bot is indeed blocking our websocket endpoint. I can share the exact IP/CNAME allowlist if you can confirm change window availability.',
    },
    recentEvents: [
        { id: 'evt-1', description: 'AI referenced “Cloudflare allowlist” procedure', ts: '08:18' },
        { id: 'evt-2', description: 'Slack #support-tier2 thread created by Dana', ts: '08:29' },
        { id: 'evt-3', description: 'Widget reconnect errors dropped by 40% (rolling 5m)', ts: '08:55' },
    ],
    sessionRecording: {
        id: 'rec_73PwZDc',
        url: '#',
        duration: '3m 14s',
    },
    sla: {
        policy: 'Enterprise urgent (1h FRT)',
        promise: 'Response in 60 min',
        timeRemaining: '32 min remaining',
        risk: 'at-risk',
    },
}
