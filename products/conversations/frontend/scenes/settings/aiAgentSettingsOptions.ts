import { TicketChannel } from '../../types'

export const CHANNEL_LABELS: Record<TicketChannel, string> = {
    widget: 'API / Widget',
    slack: 'Slack',
    email: 'Email',
    teams: 'Microsoft Teams',
    github: 'GitHub',
}

export const TICKET_TYPES = ['how_to', 'diagnostic', 'account_billing'] as const

// Only how_to replies may be sent to the customer. diagnostic/account_billing draw on project
// data, so they're locked to private notes (enforced by the backend too).
export const PUBLISHABLE_TICKET_TYPES = new Set<string>(['how_to'])

export const REPLY_MODE_OPTIONS = [
    { value: 'private_note' as const, label: 'Private note' },
    { value: 'bot_reply' as const, label: 'AI reply' },
]
