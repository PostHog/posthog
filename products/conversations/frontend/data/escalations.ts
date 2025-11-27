export type EscalationTicket = {
    id: string
    subject: string
    reason: string
    channel: 'widget' | 'slack' | 'email'
    owner: string
    minutesOpen: number
}

export const escalationTickets: EscalationTicket[] = [
    {
        id: 'CX-9102',
        subject: 'EU checkout flow failing on step 2',
        reason: 'Payment policy exception',
        channel: 'widget',
        owner: 'Dana',
        minutesOpen: 48,
    },
    {
        id: 'CX-9096',
        subject: 'API throttling for Tier X accounts',
        reason: 'Exceeded AI policy guardrail',
        channel: 'slack',
        owner: 'Sean',
        minutesOpen: 73,
    },
    {
        id: 'CX-9094',
        subject: 'Invoice download button missing',
        reason: 'High-value customer (ARR > $250k)',
        channel: 'email',
        owner: 'Priya',
        minutesOpen: 95,
    },
    {
        id: 'CX-9089',
        subject: 'SAML login loop detected',
        reason: 'Security escalation rule',
        channel: 'widget',
        owner: 'Aria',
        minutesOpen: 115,
    },
]
