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
    status: 'open' | 'pending' | 'resolved'
    priority: 'low' | 'medium' | 'high'
    channel: 'widget' | 'slack' | 'email'
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
        risk: 'on-track' | 'at-risk' | 'breached'
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
