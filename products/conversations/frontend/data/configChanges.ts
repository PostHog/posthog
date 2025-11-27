export type ConfigChange = {
    id: string
    actor: string
    description: string
    timestamp: string
    type: 'content' | 'guidance' | 'channel'
}

export const configChanges: ConfigChange[] = [
    {
        id: 'chg-101',
        actor: 'Alex Rivera',
        description: 'Enabled EU refund policy guidance pack',
        timestamp: 'Today • 09:12',
        type: 'guidance',
    },
    {
        id: 'chg-100',
        actor: 'Mei Chen',
        description: 'Updated onboarding checklist article for Series B plan',
        timestamp: 'Today • 08:47',
        type: 'content',
    },
    {
        id: 'chg-099',
        actor: 'Support bot',
        description: 'Auto-paused Slack channel #support-tier3 after 5 failures',
        timestamp: 'Yesterday • 22:14',
        type: 'channel',
    },
]
