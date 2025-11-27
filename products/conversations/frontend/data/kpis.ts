export type ConversationsKpi = {
    key: string
    label: string
    value: string
    delta: number
    deltaPeriod: string
}

export const conversationsKpis: ConversationsKpi[] = [
    {
        key: 'containment',
        label: 'AI containment rate',
        value: '72%',
        delta: 4.1,
        deltaPeriod: 'vs last 7 days',
    },
    {
        key: 'ttr',
        label: 'Median time to first response',
        value: '1m 42s',
        delta: 12.0,
        deltaPeriod: 'faster than last week',
    },
    {
        key: 'escalations',
        label: 'Escalation rate',
        value: '18%',
        delta: -2.3,
        deltaPeriod: 'vs last 7 days',
    },
    {
        key: 'sla',
        label: 'SLA breaches (24h)',
        value: '6',
        delta: -1.0,
        deltaPeriod: 'week over week',
    },
]
